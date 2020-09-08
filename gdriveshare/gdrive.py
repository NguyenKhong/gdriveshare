import httplib2
import os, sys
import logging
import time
import socket
import logging
from concurrent import futures
import threading
import json

from googleapiclient import discovery, errors
from googleapiclient.http import HttpRequest
from oauth2client import client, _helpers
from oauth2client.file import Storage

from six.moves import BaseHTTPServer
from six.moves import http_client
from six.moves import urllib

from ratelimit import limits, sleep_and_retry
from gdriveshare.utils import *


CLIENT_SECRET_FILE = "client_secrets.json"
RCLONE_CLIENT_ID = '202264815644.apps.googleusercontent.com'
RCLONE_CLIENT_SECRET = 'X4Z3ca8xfWDb1Voo-F9a7ZxJ'
SCOPES = "https://www.googleapis.com/auth/drive"
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'

HTTP_NUM_RETRIES = 5

log = logging.getLogger(__name__)


https_proxy = os.environ.get("HTTPS_PROXY", "")

if https_proxy:
    proxyInfo = httplib2.proxy_info_from_environment("https")
    httplib2.socks.setdefaultproxy(proxy_type=proxyInfo.proxy_type, 
        addr=proxyInfo.proxy_host, 
        port=proxyInfo.proxy_port, 
        rdns=proxyInfo.proxy_rdns, 
        username=proxyInfo.proxy_user, 
        password=proxyInfo.proxy_pass
    )
    httplib2.socks.wrapmodule(httplib2)

class ClientRedirectServer(BaseHTTPServer.HTTPServer):
    query_params = {}

class ClientRedirectHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(http_client.OK)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        parts = urllib.parse.urlparse(self.path)
        query = _helpers.parse_unique_urlencoded(parts.query)
        self.server.query_params = query
        self.wfile.write(
            b'<html><head><title>Authentication Status</title></head>')
        self.wfile.write(
            b'<body><p>The authentication flow has completed.</p>')
        self.wfile.write(b'</body></html>')

    def log_message(self, format, *args):
        pass


def run_flow(flow, storage):
    _FAILED_START_MESSAGE = """
    Failed to start a local webserver listening on either port 8080
    or port 8090. Please check your firewall settings and locally
    running programs that may be blocking or using those ports.
    """
    _BROWSER_OPENED_MESSAGE = """
    Your browser has been opened to visit:

        {address}

    """
    success = False
    port_number = 0
    host = "localhost"
    for port in [8080, 8090]:
        port_number = port
        try:
            httpd = ClientRedirectServer((host, port),
                                         ClientRedirectHandler)
        except socket.error:
            pass
        else:
            success = True
            break
    if not success:
        print(_FAILED_START_MESSAGE)
        sys.exit(1)
    oauth_callback = 'http://{host}:{port}/'.format(
        host=host, port=port_number)
    flow.redirect_uri = oauth_callback
    authorize_url = flow.step1_get_authorize_url()
    import webbrowser
    webbrowser.open(authorize_url, new=1, autoraise=True)
    print(_BROWSER_OPENED_MESSAGE.format(address=authorize_url))
    code = None
    httpd.handle_request()
    if 'error' in httpd.query_params:
        sys.exit('Authentication request was rejected.')
    if 'code' in httpd.query_params:
        code = httpd.query_params['code']
    else:
        print('Failed to find "code" in the query parameters of the redirect.')
        sys.exit(1)
    try:
        credential = flow.step2_exchange(code)
    except client.FlowExchangeError as e:
        sys.exit('Authentication has failed: {0}'.format(e))

    storage.put(credential)
    credential.set_store(storage)
    print('Authentication successful.')

    return credential

class HttpClient(httplib2.Http):
    # pass
    """rate limit for every http request"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.disable_ssl_certificate_validation = True
        self.timeout = 60

    @sleep_and_retry
    @limits(calls=10000, period=100)
    def request(self, *args, **kwargs):
        return super().request(*args, **kwargs)

class MemoryStorage(client.Storage):

    TEMPLATE = {"access_token": "", "client_id": "", "client_secret": "", "refresh_token": "", "token_expiry": "", "token_uri": "https://www.googleapis.com/oauth2/v4/token", "user_agent": "null", "revoke_uri": "https://accounts.google.com/o/oauth2/revoke", "id_token": "null", "id_token_jwt": "null", "token_response": {"access_token": "", "expires_in": 3599, "scope": "https://www.googleapis.com/auth/drive", "token_type": "Bearer"}, "scopes": ["https://www.googleapis.com/auth/drive"], "token_info_uri": "https://www.googleapis.com/oauth2/v3/tokeninfo", "invalid": False, "_class": "OAuth2Credentials", "_module": "oauth2client.client"}
    
    def __init__(self, rclone_token):
        super().__init__(lock = threading.Lock())
        token = self.TEMPLATE.copy()
        token["access_token"] = rclone_token["access_token"]
        token["token_response"]["access_token"] = rclone_token["access_token"]
        token["refresh_token"] = rclone_token["refresh_token"]

        token["client_secret"] = rclone_token.get("client_secret", RCLONE_CLIENT_SECRET)
        token["client_id"] = rclone_token.get("client_id", RCLONE_CLIENT_ID)

        self.buffer = json.dumps(token)

    def locked_get(self):
        credentials = None
        try:
            credentials = client.Credentials.new_from_json(self.buffer)
            credentials.set_store(self)
        except ValueError:
            pass
        return credentials

    def locked_put(self, credentials):
        self.buffer = credentials.to_json()

    def locked_delete(self):
        self.buffer = ""

class gdriveHttpRequest(HttpRequest):
    
    def __init__(self, *args, **kwargs):
        self.num_retries = kwargs.pop("num_retries", 0)
        super().__init__(*args, **kwargs)

    def execute(self, http=None, num_retries=0):
        if num_retries == 0: 
            num_retries = self.num_retries
        return super().execute(http = http, num_retries = num_retries)

class Gdrive(object):
    """docstring for Gdrive"""
    def __init__(self, rclone_token, logger = None):
        self.rclone_token = rclone_token
        self.http_pool = {}
        self.locked_http_pool = threading.Lock()
        self.credentials = self.makeCredentials()
        self.service = self.createService()

    def build_request(self, http, *args, **kwargs):
        thread_id = threading.get_ident()
        if thread_id in self.http_pool:
            new_http = self.http_pool[thread_id]
            # log.debug("Use old http request with url %s" % args[1] )
        else:
            with self.locked_http_pool:
                self.http_pool[thread_id] = self.credentials.authorize(HttpClient())
            new_http = self.http_pool[thread_id]
            # log.debug("Make new http client with url %s" % args[1])

        return gdriveHttpRequest(new_http, num_retries = HTTP_NUM_RETRIES, *args, **kwargs)

    def makeCredentials(self):
        store = MemoryStorage(self.rclone_token)
        credential = store.get()
        if not credential or credential.invalid:
            # flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
            flow = client.OAuth2WebServerFlow(CLIENT_ID, CLIENT_SECRET, SCOPES)
            credential = run_flow(flow, store)
        return credential

    def createService(self):
        service = None
        http = self.credentials.authorize(HttpClient())
        self.http_pool[threading.get_ident()] = http
        service = discovery.build("drive", "v3", http = http, requestBuilder = self.build_request)
        return service

    #=======================================================================================================================
    # utility region

    def isFolder(self, file):
        return file.get('mimeType') == "application/vnd.google-apps.folder"

    def isFile(self, file):
        return not self.isFolder(file)

    #=======================================================================================================================
    # file region

    def getFileMetadata(self, fileId):
        return self.service.files().get(fileId=fileId, fields="*", supportsAllDrives=True).execute()

    def getFiles(self, fileID = "root", items=(), query = ""):
        #sharedWithMe=true
        if items:
            items = ('id', 'name', 'mimeType') + items
        else:
            items = ('id', 'name', 'mimeType')
        if not query:
            query = "'%s' in parents and trashed=false" % fileID

        fields = 'nextPageToken, files(%s)' % ', '.join(items)
        page_token = None
        while True:
            res = self.service.files().list(q = query,
                                            fields=fields,
                                            includeItemsFromAllDrives=True,
                                            supportsAllDrives=True,
                                            pageToken=page_token).execute()
            for file in res.get('files', []):
                yield file
            page_token = res.get('nextPageToken', None)
            if page_token is None: break

    def walk(self, id = "root", more_items = ('size', 'permissions')): 
        stack = []
        id_title = "root"
        if id != "root":
            fileInfo = self.getFileMetadata(id)
            if fileInfo is None: return
            # support shared drive
            if fileInfo["name"] == "Drive" and fileInfo.get("driveId", "") != "":
                driveInfo = self.getDriveMetadata(id)
                if driveInfo is None: return
                id_title = driveInfo["name"]
            else:
                id_title = fileInfo["name"]
        top = {"id": id, "name": id_title}
        stack.append(top)

        while len(stack) != 0:
            dirs = []
            nondirs = []
            it = stack.pop()

            for file in self.getFiles(it["id"], more_items):
                #fileinfo = {"name": file["title"], "id": file["id"]}
                if self.isFolder(file):
                    dirs.append(file)
                    new_path = path_join(it["name"], file["name"])
                    stack.append({"name": new_path, "id": file["id"]})
                else:
                    nondirs.append(file)

            yield it["name"], dirs, nondirs
        return

    def subWalk(self, fileObject, more_items):
        substack = []
        dirs = []
        nondirs = []
        for file in self.getFiles(fileObject["id"], more_items):
            if self.isFolder(file):
                dirs.append(file)
                new_path = path_join(fileObject["name"], file["name"])
                substack.append({"name": new_path, "id": file["id"]})
            else:
                nondirs.append(file)
        return fileObject["name"], dirs, nondirs, substack

    def walkBulk(self, rootId, items = ()):
        id_title = "root"
        if rootId != "root":
            fileInfo = self.getFileMetadata(rootId)
            if fileInfo is None: return
            # support shared drive
            if fileInfo["name"] == "Drive" and fileInfo.get("driveId", "") != "":
                driveInfo = self.getDriveMetadata(rootId)
                if driveInfo is None: return
                id_title = driveInfo["name"]
            else:
                id_title = fileInfo["name"]

        fileObject = {"id": rootId, "name": id_title}
        stack = []
        stack.append(fileObject)
        num_worker = 5
        with futures.ThreadPoolExecutor(max_workers=num_worker) as executor:
            while len(stack):
                futures_exec = []
                i = 1
                while len(stack):
                    fileObject = stack.pop(0)
                    futures_exec.append(executor.submit(self.subWalk, fileObject, items))
                    if i >= num_worker:
                        break
                    i += 1

                while len(futures_exec):
                    future = futures_exec.pop()
                    try:
                        result = future.result(timeout=0.5)
                    except futures.TimeoutError:
                        futures_exec.append(future)
                        continue
                    if result is None: continue
                    path, dirs, nondirs, substack = result
                    stack.extend(substack)
                    yield path, dirs, nondirs
        return

    # def deleteFileToTrash(self, fileId):
        # return self.service.files().Trash(fileId = fileId).execute()
    def deleteFile(self, fileId):
        return self.service.files().delete(fileId = fileId).execute()
    #=======================================================================================================================
    # drive region

    def getDriveMetadata(self, driveId):
        return self.service.drives().get(driveId=driveId).execute()

    def getDrives(self):
        page_token = None
        query = ""
        while True:
            res = self.service.drives().list(q=query, pageToken=page_token).execute()
            for drive in res.get('drives', []):
                yield drive
            page_token = res.get('nextPageToken', None)
            if page_token is None: break

    #=======================================================================================================================
    # permission region

    def getPermission(self, file_id, permission_id):
        return self.service.permissions().get(fileId=file_id, permissionId=permission_id).execute()

    def getPermissions(self, file_id):
        return self.service.permissions().list(fileId=file_id).execute()

    def updatePermission(self, fileId, permissionId, body):

        if body.get("role") == "owner":
            return self.service.permissions().update(fileId = fileId, permissionId = permissionId, body = body, transferOwnership = True).execute()
            
        return self.service.permissions().update(fileId = fileId, permissionId = permissionId, body = body).execute()

    def deletePermission(self, file_id, permission_id):
        try:
            self.service.permissions().delete(fileId=file_id, permissionId=permission_id, fields='id').execute()
            return True
        except:
            raise
        return False

    def createPermission(self, file_id, body):
        if body.get("role") == "owner":
            return self.service.permissions().create(fileId=file_id, body=body, transferOwnership = True, fields='*').execute()
        return self.service.permissions().create(fileId=file_id, body=body, sendNotificationEmail=False, fields='*').execute()

    def sharePublic(self, file_id):
        user_permission = {
            'type': 'anyone',
            'role': 'reader',
        }
        self.service.permissions().create(fileId=file_id, body=user_permission, fields='id').execute()

    def shareUseEmail(self, file_id, email, role = "reader"):
        user_permission = {
            'type': 'user',
            'role': role,
            'emailAddress': email,
        }
        return self.service.permissions().create(fileId=file_id, body=user_permission, sendNotificationEmail=False, fields='*').execute()

    #=======================================================================================================================
    # batch request region

    def batchCallback(self, request_id, response, exception):
        if exception:
        # Handle error
            print (exception)
        else:
            print ("file %s update new permission" % response.get('name'))

    def batchRequest(self, requests):
        batch = self.service.new_batch_http_request(callback = self.batchCallback)
        for request in requests:
            batch.add(request)
        batch.execute()

