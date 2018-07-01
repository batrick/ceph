#!/usr/bin/env python2

import argparse
import codecs
import csv
import json
import logging
import os
import re
import requests
import sys
import time
from datetime import datetime

from os.path import expanduser

log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)

with open(expanduser("~/.github.key")) as f:
    PASSWORD = f.read().strip()

CONTRIBUTORS = {}
with codecs.open(".githubmap", encoding='utf-8') as f:
    comment = re.compile("\s*#")
    patt = re.compile("([\w-]+)\s+(.*)")
    for line in f:
        if comment.match(line):
            continue
        m = patt.match(line)
        CONTRIBUTORS[m.group(1)] = m.group(2)

with codecs.open(".contributormap.csv", encoding='utf-8') as f:
    dialect = csv.Sniffer().sniff(f.read(1024))
    f.seek(0)
    r = csv.reader(f, dialect, delimiter=str(u',').encode('utf-8'), quotechar=str(u'"'.encode('utf-8')))
    # need to read first row, then use that row to output dicts w/ key/values
    header = r.next()
    CMAP = {}
    for row in r:
        CMAP[username] = {
            ...
        }
    sys.exit(0)

def build_map(args):
    cmap = {}
    with codecs.open('.contributormap.csv', 'w', encoding='utf-8') as f:
        f.write('#"GitHub Username","Last Fetched","Full Name","URL","Company","Location"\n')
        for username, name in CONTRIBUTORS.viewitems():
            time.sleep(5)
            log.info("getting data for {u}".format(u=username))
            t = datetime.utcnow().isoformat()
            info = requests.get("https://api.github.com/users/{user}".format(user=username))
            if info.status_code == 403:
                log.error("fatal error: {r}".format(r=info))
                sys.exit(1)
            elif info.status_code != 200:
                log.error("user '{user}' not found: {r}".format(user=username,r=info))
                continue
            info = info.json()
            if info['location'] == 'None':
                info['location'] = 'Antarctica'
            cmap[username] = {
                'name': name,
                'url': info['html_url'],
                'company': info['company'],
                'location': info['location'],
            }
            c = cmap[username]
            f.write(u'"{u}","{t}","{n}","{url}","{c}","{l}"\n'.format(u=username,t=t,n=c['name'],url=c['url'],c=c['company'],l=c['location']))
            break

def main():
    parser = argparse.ArgumentParser(description="Ceph Contributor Map tool")
    #parser.add_argument('--branch', dest='branch', action='store', default=default_branch, help='branch to create ("HEAD" leaves HEAD detached; i.e. no branch is made)')
    #args = parser.parse_args(sys.argv)
    args = sys.argv
    return build_map(args)

if __name__ == "__main__":
    main()
