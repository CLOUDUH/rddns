# router-ddns

Router WAN IP address DDNS
Based on [NewFuture/DDNS](https://github.com/NewFuture/DDNS)

## Usage

> Use TP-LINK router, not suitable for other routers. If you use other routers, you can modify the code yourself.

1. Download/Clone this repository
2. Change the `config.json` file, and copy it to other places
3. Upload this folder to your NAS, and upload the `config.json` file to the other places
4. SSH connect to your NAS, and cd to this folder
5. Build docker image
6. Open your nas, and run docker image
7. config environment variables`volumex/docker/xxxx/config.json` to `/config.json` in docker
8. go and enjoy it

## About config.json

router: router ip address like "http://192.168.1.1/"
rpwd: not your password, you can checkout F12-Network-192.168.X.X-Request Payload-{method:do,login:{password:xxxxx}}

You can refer to the [NewFuture/DDNS](https://github.com/NewFuture/DDNS)

And I added a `router` and `rpwd` to config.json

if you want to change it, please change it in the `config.json` and `scheme.json` file

## About request router ip

I modify the `run.py` file

login_router
request_wan_ip
get_ip


