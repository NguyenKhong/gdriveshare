import argparse
import sys
from textwrap import dedent
import logging

def num(type, min=None, max=None):
    def func(value):
        value = type(value)

        if min is not None and not (value > min):
            raise argparse.ArgumentTypeError(
                '{0} value must be more than {1} but is {2}'.format(
                    type.__name__, min, value
                )
            )

        if max is not None and not (value <= max):
            raise argparse.ArgumentTypeError(
                '{0} value must be at most {1} but is {2}'.format(
                    type.__name__, max, value
                )
            )

        return value

    func.__name__ = type.__name__

    return func

class HelpFormatter(argparse.HelpFormatter):
    """A nicer help formatter.

    Help for arguments can be indented and contain new lines.
    It will be de-dented and arguments in the help will be
    separated by a blank line for better readability.

    Originally written by Jakub Roztocil of the httpie project.
    """

    def __init__(self, max_help_position=10, *args, **kwargs):
        # A smaller indent for args help.
        # kwargs["max_help_position"] = max_help_position
        super().__init__(*args, **kwargs)

    def _split_lines(self, text, width):
        import textwrap
        text = dedent(text).strip() + "\n\n"
        result = []

        for subtext in text.splitlines():
            result.extend(textwrap.wrap(subtext, width))
        result.append("")
        return result
        # return [textwrap.wrap(subtext, width) for subtext in text.splitlines()]
        # return text.splitlines()

def buildParser():
    print ("")

    hidden_parser = argparse.ArgumentParser(add_help=False)
    hidden_parser.add_argument("-c", "--rclone-config",
        type=str,
        metavar="PATH",
        help="""
        Path to rlcone config file.
        """
    )


    hidden_parser.add_argument("-t", "--request-threads",
        type=num(int, max=10),
        metavar="THREADS",
        default=5,
        help="""
        The number of parallelism request to the api server.
        Default is 5.
        """
    )

    hidden_parser.add_argument("-l", "--loglevel",
        choices=[name.lower() for _, name in logging._levelToName.items()],
        metavar="LEVEL",
        default="info",
        help="""
        Set the log message threshold.
        Valid levels are: %s.
        Default is info.
        """ % (", ".join([name.lower() for _, name in logging._levelToName.items()]))
    )

    hidden_parser.add_argument("--log-path",
        type=str,
        metavar="PATH",
        help="""
        Save log to file.
        """
    )
    parser = argparse.ArgumentParser(
        prog="gdrivepermissions",
        parents=[hidden_parser],
        formatter_class=HelpFormatter,
        usage="gdrivepermissions [OPTIONS] <COMMAND> <remote:path>",
        description="""
            The program is command-line utility that support for rclone.
            This utility makes working with google drive permission easier.
            """
    )
    #==================================================================
    command_parser = parser.add_subparsers(metavar="", title="COMMAND", dest="command" )

    #-----------------------------------------------------------------
    share_parser = command_parser.add_parser(
        "share",
        parents=[hidden_parser],
        usage="gdrivepermissions share <remote:path> [OPTIONS]",
        formatter_class=HelpFormatter,
        help="""
            Use command `share email` to active share file or folder with email.
            User command `share anyone` to share with anyone.
            Default is anyone.
            """
    )
    share_parser.add_argument(
        "remote",
        metavar="remote",
        nargs="?",
        # required=True,
        help="""
        The remote is a file or folder, which you want share. 
        """
    )
    share_parser.add_argument(
        "-e", "--email",
        metavar="email|anyone",
        default="anyone",
        nargs="?",
        help="""
        Share file or folder by email.
        Default, the file or folder will be shared to anyone.
        """
    )
    share_parser.add_argument(
        "-r", "--role",
        metavar="reader|writer",
        choices=["reader", "writer"],
        default="reader",
        nargs="?",
        help="""
        The role of user.
        Role: reader, writer.
        Default is reader.
        """
    )

    #-----------------------------------------------------------------
    del_parser = command_parser.add_parser(
        "del",
        parents=[hidden_parser],
        usage="gdrivepermissions del <remote:path> [OPTIONS]",
        formatter_class=HelpFormatter,
        help="""
            Use command `del email` to remove permission file or folder.
            User command `del anyone` to remove permission anyone.
            Default is anyone.
            """
    )
    del_parser.add_argument(
        "remote",
        metavar="remote",
        nargs="?",
        help="""
        The remote is a file or folder, which you want remove permission. 
        """
    )
    del_parser.add_argument(
        "-e", "--email",
        metavar="email|anyone",
        default="anyone",
        nargs="?",
        help="""
        Remove permission by email.
        Default, file or folder will be disable public share.
        """
    )

    return parser, share_parser, del_parser

def main():
    parser, share_parser, del_parser = buildParser()
    args = parser.parse_args()
    if len(sys.argv) <= 1:
        parser.print_help()

    print (args.request_threads)
    if args.rclone_config:
        print (args.rclone_config)
    else:
        args.rclone_config = "acccc"
        print (args.rclone_config)

    if args.command == "share":
        if not args.remote:
            share_parser.print_help()
            return
    if args.command == "del":
        if not args.remote:
            del_parser.print_help()
            return

if __name__ == '__main__':
    main()
