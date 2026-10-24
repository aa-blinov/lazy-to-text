import subprocess, os, sys, time, signal
S="/private/tmp/claude-501/sec-final"; W="/Users/justcomex/Documents/Проекты/pet/lazy-to-text/.claude/worktrees/llm-reasoning-tokens-config-624055"
env=dict(os.environ,HOME=S+"/home",PYTHONPATH=W)
def run(label,*args):
    p=subprocess.Popen([W+"/.venv/bin/python","-m","app.server","--no-single-instance","--no-stdin-watch","--token","t","--port","0",*args],cwd=S,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try: out,err=p.communicate(timeout=8); st="exit %s"%p.returncode
    except subprocess.TimeoutExpired:
        p.terminate()
        try: out,err=p.communicate(timeout=10)
        except subprocess.TimeoutExpired: p.kill(); out,err=p.communicate()
        st="running"
    bad=[l for l in err.splitlines() if not l.startswith(("INFO","WARNING:app"))][-4:]
    print(f"== {label}: {st} | out={out.strip()[:80]!r} | err={' / '.join(bad)[:400]}")
os.chdir(S)
run("nested new, spaces, unicode", "--data-dir", S+"/dd-new/a/b c/ü")
run("path is a file", "--data-dir", S+"/dd-file")
run("read-only dir", "--data-dir", S+"/dd-ro")
run("symlink", "--data-dir", S+"/dd-link")
run("relative", "--data-dir", "rel-dd")
run("tilde", "--data-dir", "~/tilde-dd")
run("dotdot", "--data-dir", S+"/dd-new/../dd-dot")
run("newline", "--data-dir", S+"/dd-nl\nx")
run("empty", "--data-dir", "")
run("env var", ) if False else None
