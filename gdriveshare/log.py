import logging
import os, sys

logger = logging.getLogger("gdriveshare")

def setupLogger(args):

    logger.setLevel(args.loglevel.upper())
    stdout_logger = logging.StreamHandler()
    stdout_formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    stdout_logger.setFormatter(stdout_formatter)
    logger.addHandler(stdout_logger)
    
    logpath = ""
    if args.log_path:
        if os.path.isdir(args.log_path):
            filename = sys.argv[0]
            filename = filename[:filename.rfind(".")]
            logpath = os.path.join(args.log_path, filename + ".log")
        else:
            logpath = args.log_path

    if args.loglevel.upper() == "DEBUG":
        filename = sys.argv[0]
        filename = filename[:filename.rfind(".")]
        logpath = filename + ".log"

    if logpath:
        file_logger = logging.FileHandler(logpath, 'a', 'utf-8')
        file_formatter = logging.Formatter('%(asctime)s %(module)s %(funcName)s %(levelname)s: %(message)s')
        file_logger.setFormatter(file_formatter)
        logger.addHandler(file_logger)