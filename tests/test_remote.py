from tests_by_bug_id import all_tests
from util.env.logs import Log

url = "http://klahnakoski-es.corp.tor1.mozilla.com:9201"

try:
    all_tests(url)
finally:
    Log.stop()
