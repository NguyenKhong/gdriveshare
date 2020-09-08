import os
from urllib.parse import urljoin, urlparse
import urllib
import ntpath

is_win32 = os.name == "nt"

def createDirectory(base, new_dir):
    if is_win32:
        new_dir = cleanName(new_dir, ".")
        if not base.startswith("\\\\?\\"): base = "\\\\?\\" + base
    path_new_dir = os.path.join(base, new_dir)
    if not os.path.exists(path_new_dir): os.mkdir(path_new_dir)
    return path_new_dir

def longPath(path):
    if is_win32 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + path
    return path

def try_get(src, getter, expected_type=None):
    if not isinstance(getter, (list, tuple)):
        getter = [getter]
    for get in getter:
        try:
            
            v = get(src)
        except (AttributeError, KeyError, TypeError, IndexError):
            pass
        else:
            if expected_type is None or isinstance(v, expected_type):
                
                return v
    return None

def cleanName(value, deletechars = '<>:"/\\|?*\r\n'):
    value = str(value)
    for c in deletechars:
        value = value.replace(c,'')
    return value

def GetFileNameFromUrl(url):
    urlParsed = urlparse(urllib.parse.unquote(url))
    fileName = os.path.basename(urlParsed.path).encode('utf-8')
    return cleanName(fileName)

def pathLeaf(path):
    '''
    Name..........: pathLeaf
    Description...: get file name from full path
    Parameters....: path - string. Full path
    Return values.: string file name
    Author........: None
    '''
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)

def path_join(*args):
    new_path = os.path.join(*args)
    if os.path.altsep:
        return new_path.replace(os.path.sep, os.path.altsep)
    return new_path