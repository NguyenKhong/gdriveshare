# GDRIVE SHARE 
The program is command-line utility that support for rclone. This utility makes working with google drive permission easier.

## Installtion
* The first install python 3
* git clone https://github.com/NguyenKhong/gdriveshare.git
* cd gdriveshare
* pip -r requirements.txt

## Quickstart
Run command:
```
python3 gdriveshare_cli.py -c <path to rclone config file> <COMMAND> <remote:path>
```
With command:
- **share**
- **del**

And the remote was defined in the rclone config file. 

For more detail. please run: `python gdriveshare_cli.py -h` or `python gdriveshare_cli.py <COMMAND> -h`

## Example
* Share directory **foo** with remote is **gdrive** to anyone can be readable.
	```
	python gdriveshare_cli.py share gdrive:/foo
	```
* Share directory **foo** with remote is **gdrive** to **email foo@gmail.com** and can be **writeable**.
	```
	python gdriveshare_cli.py share gdrive:/foo -e foo@gmail.com -r writer
	```

The delete command is similar to the share command.

## End