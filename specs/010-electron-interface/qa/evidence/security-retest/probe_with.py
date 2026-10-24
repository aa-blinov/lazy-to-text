import sys
sys.path.insert(0,"/private/tmp/claude-501/sec-retest/proj")
import app.privacy_env
exec(open(sys.argv[3]).read())
