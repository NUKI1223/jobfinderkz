"""Verify Docker DNS changes through the built nginx image on an isolated network."""
import ipaddress
import json
import subprocess
import time

network='jobfinder-audit-dns'
containers=[]


def run(*args):
    return subprocess.check_output(['docker',*args],text=True,stderr=subprocess.PIPE).strip()


def server(name, address, message):
    code=f'''from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200); self.end_headers(); self.wfile.write({message.encode()!r})
 def log_message(self,*args): pass
HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
'''
    run('run','-d','--name',name,'--network',network,'--network-alias','api','--ip',address,
        'jobfinderkz-backend:local','python','-c',code)
    containers.append(name)


def expect(message):
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        try:
            value=run('exec','jobfinder-audit-dns-web','wget','-qO-','http://127.0.0.1/api/v1/health')
            if value==message:return
        except subprocess.CalledProcessError:
            pass
        time.sleep(1)
    raise AssertionError('nginx did not resolve the replacement API address')


if __name__=='__main__':
    run('network','create',network)  # Refuse an existing test network.
    try:
        subnet=json.loads(run('network','inspect',network))[0]['IPAM']['Config'][0]['Subnet']
        base=ipaddress.ip_network(subnet).network_address
        server('jobfinder-audit-dns-old',str(base+2),'first')
        run('run','-d','--name','jobfinder-audit-dns-web','--network',network,'jobfinderkz-web')
        containers.append('jobfinder-audit-dns-web')
        expect('first')
        run('rm','-f','jobfinder-audit-dns-old');containers.remove('jobfinder-audit-dns-old')
        server('jobfinder-audit-dns-new',str(base+4),'replacement')
        expect('replacement')
        print('PASS: nginx resolves a changed API IP without restarting nginx')
    finally:
        for name in reversed(containers):run('rm','-f',name)
        run('network','rm',network)
