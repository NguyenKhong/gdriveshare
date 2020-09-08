import os, sys
from configparser import ConfigParser
import json
import re
import time
import logging
import signal

# import gdriveshare
from gdriveshare.gdrive import Gdrive
from gdriveshare.driverequests import ShareUseEmailRequest, DeletePermissionRequest, BulkRequestFactory
from gdriveshare.accounting import Accounting
from gdriveshare.log import setupLogger
from gdriveshare import ipipe
from argparser import buildParser


log = logging.getLogger("gdriveshare.cli")

def loadConfig(path):
    config = ConfigParser()
    config.read(path)
    return config

re_input_id = re.compile(r"^id:([a-zA-Z0-9_-]{28,})")
def processInput(data):
    driveName, path = data.split(":", 1)
    matchId = re_input_id.match(path)
    if matchId:
        return driveName, path, matchId[1]
    return driveName, path, None

def getDriveConfig(section):

    driveToken = json.loads(section["token"])
    driveConfig = {"client_id": section.get("client_id", ""),
                    "client_secret": section.get("client_secret", ""),
                    "root_folder_id": section["root_folder_id"] or "root",
                    "access_token": driveToken["access_token"],
                    "refresh_token": driveToken["refresh_token"]
                }
    return driveConfig

def processPath2Id(driveClient: Gdrive, rootId: str, path: str):
    if path == "" or path == "/":
        return rootId
    pathsplit = path.split("/")
    srcId = rootId
    while len(pathsplit):
        pathName = pathsplit.pop(0)
        while not pathName:
            pathName = pathsplit.pop(0)
        file = next(driveClient.getFiles(query = "'%s' in parents and name='%s' and trashed=false" % (srcId, pathName.replace("'", "\\'"))), None)
        if file:
            srcId = file["id"]
        else:
            srcId = None
            break
    return srcId

def sharePermission(args):
    config = loadConfig(args.rclone_config)
    driveName, path, driveId = processInput(args.remote)
    if driveName not in config:
        print ("The remote is not found.")
        sys.exit(2)
    driveSection = config[driveName]
    driveConfig = getDriveConfig(driveSection)
    driveClient = Gdrive(driveConfig)

    rootFoldedId = None
    if driveId:
        rootFoldedId = driveId
    else:
        rootFoldedId = processPath2Id(driveClient, driveConfig["root_folder_id"], path)

    if not rootFoldedId:
        print("The root folder id not found.")
        sys.exit(3)

    batchPipe = ipipe.Ipipe()
    driveRequest = ShareUseEmailRequest(driveClient, args.email, role=args.role)
    accounting = Accounting(batchPipe)

    sender = BulkRequestFactory(args.request_threads, driveClient, batchPipe, driveRequest, accounting)
    sender.run()
    num_job = 0
    if rootFoldedId != "root":
        file = driveClient.getFileMetadata(rootFoldedId)
        batchPipe.put({"file": file})
        num_job += 1

    for path, dirs, files in driveClient.walkBulk(rootFoldedId, ('size', 'permissions')):
        for directory in dirs:
            batchPipe.put({"file": directory})
            num_job += 1
        for file in files:
            batchPipe.put({"file": file})
            num_job += 1
  
    batchPipe.close()
    log.debug("The number of jobs: %d" % num_job)
    sender.wait()
    accounting.shutdown()

def deletePermission(args):
    config = loadConfig(args.rclone_config)
    driveName, path, driveId = processInput(args.remote)
    if driveName not in config:
        print ("The remote is not found.")
        sys.exit(2)
    driveSection = config[driveName]
    driveConfig = getDriveConfig(driveSection)
    driveClient = Gdrive(driveConfig)

    rootFoldedId = None
    if driveId:
        rootFoldedId = driveId
    else:
        rootFoldedId = processPath2Id(driveClient, driveConfig["root_folder_id"], path)

    if not rootFoldedId:
        print("The root folder id not found.")
        sys.exit(3)

    batchPipe = ipipe.Ipipe()
    driveRequest = DeletePermissionRequest(driveClient, args.email)
    accounting = Accounting(batchPipe)
    sender = BulkRequestFactory(args.request_threads, driveClient, batchPipe, driveRequest, accounting)
    sender.run()
    num_job = 0
    if rootFoldedId != "root":
        file = driveClient.getFileMetadata(rootFoldedId)
        batchPipe.put({"file": file})
        num_job += 1

    for path, dirs, files in driveClient.walkBulk(rootFoldedId, ('size', 'permissions')):
        for directory in dirs:
            batchPipe.put({"file": directory})
            num_job += 1
        for file in files:
            batchPipe.put({"file": file})
            num_job += 1
  
    batchPipe.close()
    log.debug("The number of jobs: %d" % num_job)
    sender.wait()
    accounting.shutdown()

def HomeDir():
    
    home = os.environ.get("HOME", "") or os.environ.get("home", "")
    if home: return home
    if sys.platform.startswith("win"):
        home = os.environ.get("USERPROFILE", "")
        if home: return home
        drive = os.environ.get("HOMEDRIVE", "")
        path = os.environ.get("HOMEPATH", "")
        if drive and path:
            return drive + path
    return ""

def findRcloneConfig():

    configFileName = "rclone.conf"
    hiddenConfigFileName = "." + configFileName

    homeDir = HomeDir()
    cfgdir = ""
    xdgdir = os.environ.get("XDG_CONFIG_HOME", "")
    if xdgdir:
        cfgdir = os.path.join(xdgdir, "rclone")
    elif homeDir:
        cfgdir = os.path.join(homeDir, ".config", "rclone")

    cfgpath = os.path.join(cfgdir, configFileName)
    if os.path.exists(cfgpath):
        return cfgpath

    if homeDir:
        cfgpath = os.path.join(homeDir, hiddenConfigFileName)
        if os.path.exists(cfgpath):
            return cfgpath

    print ("The file config rclone is not found.\nPlease enter command `rclone config file` to show file path.")
    sys.exit(1)

def signalHander(sig, frame):
    print ("Stop program!")
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, signalHander)
    parser, share_parser, del_parser = buildParser()
    args = parser.parse_args()
    if len(sys.argv) <= 1:
        parser.print_help()
        sys.exit(0)

    if args.command == "share" and not args.remote:
        share_parser.print_help()
        sys.exit(0)

    if args.command == "del" and not args.remote:
        share_parser.print_help()
        sys.exit(0)

    if not args.rclone_config:
        args.rclone_config = findRcloneConfig()
    elif not os.path.exists(args.rclone_config):
        print ("The file %s is not exists." % args.rclone_config)
        sys.exit(1)

    setupLogger(args)

    if args.command == "share":
        sharePermission(args)

    if args.command == "del":
        deletePermission(args)
    


if __name__ == '__main__':
    main()