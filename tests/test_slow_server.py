# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from _subprocess import CREATE_NEW_PROCESS_GROUP
import subprocess

from flask import Flask, Response
import flask
import signal
import time
import requests
from werkzeug.exceptions import abort
from esFrontLine.app import stream
from util.cnv import CNV
from util.env.logs import Log
from util.strings import expand_template
from util.thread.threads import Thread, Signal

app = Flask(__name__)

WHITELISTED = "public_bugs"  # ENSURE THIS IS IN THE slow_server_settings.json WHITELIST

PATH = '/'+WHITELISTED+'/_mapping'
SLOW_PORT = 9299
PROXY_PORT = 9298
RATE = 4.0   # per second
proxy_is_ready = Signal()
server_is_ready = Signal()


@app.route('/', defaults={'path': ''}, methods=['GET'])
@app.route('/<path:path>', methods=['GET'])
def serve_slowly(path):
    def octoberfest():
        for bb in range(99, 2, -1):
            yield ("0"*65535)+"\n"  # ENOUGH TO FILL THE INCOMING BUFFER
            Thread.sleep(1.0/RATE)
            yield CNV.unicode2utf8(expand_template("{{num}} bottles of beer on the wall! {{num}} bottles of beer!  Take one down, pass it around! {{less}} bottles of beer on he wall!\n", {
                "num": bb,
                "less": bb - 1
            }))
        yield ("0"*65535)+"\n"  # ENOUGH TO FILL THE INCOMING BUFFER
        yield CNV.unicode2utf8(u"2 bottles of beer on the wall! 2 bottles of beer!  Take one down, pass it around! 1 bottle of beer on he wall!\n")
        yield ("0"*65535)+"\n"  # ENOUGH TO FILL THE INCOMING BUFFER
        yield CNV.unicode2utf8(u"1 bottle of beer on the wall! 1 bottle of beer!  Take one down, pass it around! 0 bottles of beer on he wall.\n")

    try:
        ## FORWARD RESPONSE
        return Response(
            octoberfest(),
            direct_passthrough=True, #FOR STREAMING
            status=200
        )
    except Exception, e:
        abort(400)


def run_slow_server(please_stop):
    proc = subprocess.Popen(
        ["python", "tests\\test_slow_server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=-1,
        creationflags=CREATE_NEW_PROCESS_GROUP
    )

    while not please_stop:
        line = proc.stdout.readline()
        if not line:
            continue
        if line.find(" * Running on") >= 0:
            server_is_ready.go()
        Log.note("SLOW SERVER: "+line)

    proc.send_signal(signal.CTRL_C_EVENT)


def run_proxy(please_stop):
    proc = subprocess.Popen(
        ["python", "esFrontLine\\app.py", "--settings", "tests/resources/slow_server_settings.json"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=-1,
        creationflags=CREATE_NEW_PROCESS_GROUP
    )

    while not please_stop:
        line = proc.stdout.readline()
        if not line:
            continue
        if line.find(" * Running on") >= 0:
            proxy_is_ready.go()
        Log.note("PROXY: {{line}}", {"line": line.strip()})

    proc.send_signal(signal.CTRL_C_EVENT)


def test_slow_streaming():
    """
    TEST THAT THE app ACTUALLY STREAMS.  WE SHOULD GET A RESPONSE BEFORE THE SERVER
    FINISHES DELIVERING
    """
    slow_server_thread = Thread.run("run slow server", run_slow_server)
    proxy_thread = Thread.run("run proxy", run_proxy)

    try:
        proxy_is_ready.wait_for_go()
        server_is_ready.wait_for_go()

        start = time.clock()
        response = requests.get("http://localhost:"+str(PROXY_PORT)+PATH, stream=True)
        for i, data in enumerate(stream(response.raw)):
            Log.note("CLIENT GOT RESPONSE:\n{{data|indent}}", {"data": data})
            end = time.clock()
            if i == 0 and end - start > 10:  # IF WE GET DATA BEFORE 10sec, THEN WE KNOW WE ARE STREAMING
                Log.error("should have something by now")
        if response.status_code != 200:
            Log.error("Expecting a positive response")

    except Exception, e:
        Log.error("Not expected", e)
    finally:
        slow_server_thread.please_stop.go()
        proxy_thread.please_stop.go()


if __name__ == "__main__":
    #THIS WILL RUN THE SLOW SERVER
    app.run(
        host="0.0.0.0",
        port=SLOW_PORT,
        debug=False,
        threaded=False,
        processes=1
    )
