from googleapiclient.http import _should_retry_response
# import itertools 
import logging
from threading import Thread, Lock
# import queue
import atexit
import time
from gdriveshare import ipipe

MAX_RETRY_PER_REQUEST = 5

log = logging.getLogger(__name__)

'''
class BatchRequestSender(Thread):

    def __init__(self, driveClient, pipe, driveRequest):
        self.driveClient = driveClient
        self.pipe = pipe
        self.close = False
        super().__init__(daemon=True)
        self.requestId = 0
        self.requests = []
        self.redoRequests = []
        self.thresholdRequestPerBatch = 50
        self.driveRequest = driveRequest
        if not isinstance(self.driveRequest, DriveRequest):
            raise Exception("The argument driveRequest must be inheritance class DriveRequest")
        atexit.register(self.shutdown)

    def callback(self, request_id, response, exception):
        requestId = int(request_id)
        if exception: 
            if _should_retry_response(exception.resp.status, exception.content) and self.requests[requestId].retry < MAX_RETRY_PER_REQUEST:
                log.error("Retry the file Id %s - requestId %s was failed because %s" % (self.requests[requestId].options.get("id", ""), request_id, exception.resp.status))
                self.requests[requestId].retry += 1
                self.redoRequests.append(self.requests[requestId])
            else:
                log.error("The file Id %s - requestId %s was failed because %s" % (self.requests[requestId].options.get("id", ""), request_id, exception.resp.status))
        self.driveRequest.processResponse(self.requests[requestId], response, exception)

    def newBatch(self, requests):
        batch = self.driveClient.service.new_batch_http_request(callback = self.callback)
        for extraRequest in requests:
            log.debug("requestId %d - file id %s" % (self.requestId, extraRequest.options.get("id", "")))
            batch.add(extraRequest.request, request_id = str(self.requestId))
            self.requestId += 1
        batch.execute()

    def __chunks(self, data, size):
        for i in range(0, len(data), size):
            yield data[i:i+size]

    def splitBatch(self):
        self.requestId = 0
        log.debug("Start split with number of requests %d" % len(self.requests))
        for requests in self.__chunks(self.requests, self.thresholdRequestPerBatch):
            self.newBatch(requests)
        log.debug("End split with RequestId from 0 to %d" % (self.requestId-1) )
        self.requests = self.redoRequests
        self.redoRequests = []

    def run(self):
        while True:
            if self.close: return
            if len(self.requests) >= self.thresholdRequestPerBatch:
                self.splitBatch()
            try:
                obj = self.pipe.get(timeout = 0.5)
            except ipipe.Empty:
                continue
            except ipipe.Closed:
                log.debug("Split requests and exit thread")
                while len(self.requests) and self.close == False:
                    log.debug("loop to empty")
                    self.splitBatch()
                return
            # self.requests[self._newId()] = self.driveRequest.build(obj)
            extraRequest = self.driveRequest.build(obj)
            if extraRequest:
                self.requests.append(extraRequest)
                log.debug("Add new extraRequest")
            # except DriveRequestError:
            #     continue

    def shutdown(self):
        self.close = True

    def join(self):
        while self.is_alive():
            super().join(1)
'''

class BulkRequestFactory(object):
    """docstring for BulkRequst"""
    def __init__(self, worker, driveClient, pipe, driveRequest, accounting):
        self.workers = []
        for _ in range(worker):
            t = BulkRequest(driveClient, pipe, driveRequest, accounting)
            self.workers.append(t)

    def run(self):
        for w in self.workers:
            w.start()

    def wait(self):
        for w in self.workers:
            w.join()

    def close(self):
        for w in self.workers:
            w.shutdown()

class BulkRequest(Thread):

    def __init__(self, driveClient, pipe, driveRequest, accounting):
        self.driveClient = driveClient
        self.pipe = pipe
        self.close = False
        super().__init__(daemon=True)
        self.driveRequest = driveRequest
        if not isinstance(self.driveRequest, DriveRequest):
            raise Exception("The argument driveRequest must be inheritance class DriveRequest")
        atexit.register(self.shutdown)
        self.accounting = accounting

    def run(self):
        self.accounting.increaseJobdoing()
        self._run()
        self.accounting.decreaseJobdoing()

    def _run(self):
        while True:
            if self.close: return
            try:
                obj = self.pipe.get(timeout = 0.5)
            except ipipe.Empty:
                continue
            except ipipe.Closed:
                return
            
            extraRequest = self.driveRequest.build(obj)
            if extraRequest:
                log.debug("Add new extraRequest")
                resp = None
                exception = None
                try:
                    resp = extraRequest.request.execute()
                    self.accounting.JobComplete()
                except Exception as err:
                    self.accounting.JobFailed()
                    exception = err
                self.driveRequest.processResponse(extraRequest, resp, exception)
            else:
                self.accounting.JobComplete()

    def shutdown(self):
        self.close = True

    def join(self):
        while self.is_alive():
            super().join(1)

class ExtraRequest(object):
    def __init__(self, request, options):
        self.request = request
        self.options = options
        self.retry = 0

class DriveRequest(object):
    def __init__(self, driveClient):
        self.driveClient = driveClient

    def _build(self):
        raise NotImplementedError

    def build(self, obj):
        result = self._build(obj)
        if not result:
            return None
        request, options = result 
        return ExtraRequest(request, options)

    def processResponse(self, extraRequest, response, exception):
        pass

class DeletePermissionRequest(DriveRequest):

    def __init__(self, driveClient, email):
        super().__init__(driveClient)
        self.email = email

    def email2PermissionId(self, file):
        fileFiltered = next(filter(lambda permission: permission.get("emailAddress", "") == self.email, file["permissions"]), None)
        if fileFiltered:
            return fileFiltered["id"]
        return None

    def _build(self, obj):
        file = obj["file"]
        permissionId = self.email2PermissionId(file)
        if not permissionId:
            return None
        request = self.driveClient.service.permissions().delete(fileId=file["id"], permissionId=permissionId, fields='id')
        options = {"filename": file["name"]}
        return request, options

    def processResponse(self, extraRequest, response, exception):
        if exception:
            log.error("%s", exception)
        else:
            log.info("Delete permission of file id %s was successfully" % extraRequest.options.get("filename"))

class ShareUseEmailRequest(DriveRequest):

    CREATE = 0
    UPDATE = 1

    def __init__(self, driveClient, email, role = "reader"):
        super().__init__(driveClient)
        self.email = email
        self.role = role

    def filterPermission(self, file):

        finded = False
        for permission in file["permissions"]:
            if permission.get("emailAddress", "") == self.email or permission.get("type", "") == self.email: # case share with anyone
                if permission.get("role") != self.role:
                    return self.UPDATE, file, permission
                else:
                    finded = True # email and role are exists

        if not finded:
            return self.CREATE, file, None
        return None, None, None

    def requestCreatePermission(self, file_id):
        user_permission = {
            'type': 'user',
            'role': self.role,
            'emailAddress': self.email,
        }
        if self.email == "anyone":
            user_permission["type"] = "anyone"
            del user_permission["emailAddress"]

        return self.driveClient.service.permissions().create(fileId=file_id, body=user_permission, sendNotificationEmail=False, fields='id')

    def requestUpdatePermission(self, file_id, permission):
        user_permission = {
            'role': self.role,
        }
        # if self.email == "anyone":
            # user_permission["type"] = "anyone"
            # del user_permission["emailAddress"]

        return self.driveClient.service.permissions().update(fileId=file_id, body=user_permission, permissionId=permission["id"], fields='id')

    def _build(self, obj):
        mode, file, permission = self.filterPermission(obj["file"])
        if mode == self.CREATE:
            request = self.requestCreatePermission(file["id"])
            return request, {"filename": file["name"]}
        elif mode == self.UPDATE:
            request = self.requestUpdatePermission(file["id"], permission)
            return request, {"filename": file["name"]}
        return None

    def processResponse(self, extraRequest, response, exception):
        if exception:
            log.error("%s", exception)
        else:
            log.info ("Share file %s was successfully" % extraRequest.options.get("filename"))

# class ShareAnyoneRequest(DriveRequest):

#     def filterPermissionExsist(self, file):
#         if not next(filter(lambda permission: permission.get("type", "") == "anyone", file["permissions"]), None):
#             return file
#         return None


#     def sharePublic(self, file_id):
#         user_permission = {
#             'type': 'anyone',
#             'role': 'reader',
#         }
#         return self.driveClient.service.permissions().create(fileId=file_id, body=user_permission, fields='id')

#     def _build(self, obj):
#         file = self.filterPermissionExsist(obj["file"])
#         if file:
#             request = self.sharePublic(file["id"])
#             return request, {"filename": file["name"], "id": file["id"]}
#         return None

#     def processResponse(self, extraRequest, response, exception):
#         if not exception:
#             # print ("Share file %s was successfully" % extraRequest.options.get("filename"))
#             log.info ("Share file %s - file id %s was successfully" % (extraRequest.options.get("filename"), extraRequest.options.get("id", "")))
