
import os, sys, glob, subprocess, shutil
HERE=os.path.dirname(os.path.abspath(__file__)); BASE=r"C:\GHL\2026 yeosu"
SUB=os.environ.get("RAWSUB","hot")
ALL=sorted(glob.glob(os.path.join(BASE,"RAW",SUB,"*","*.dat"))); names=[os.path.basename(p) for p in ALL]
def day_job(ch, mode, rt, day, outroot, purge):
    idx=[i for i,n in enumerate(names) if n.startswith(day)]
    if not idx: return
    lo=max(0,idx[0]-1); hi=min(len(ALL),idx[-1]+2)
    files=ALL[lo:hi]
    tmp=os.path.join(outroot,"_tmp",f"ch{ch}_{day}"); os.makedirs(tmp,exist_ok=True)
    subprocess.run([sys.executable,os.path.join(HERE,"alpha_run.py"),str(ch),mode,rt,tmp,str(purge)]+files,check=True)
    dst=os.path.join(outroot,os.environ.get("CHDIR",f"ch{ch}"),day); os.makedirs(dst,exist_ok=True)
    for f in glob.glob(os.path.join(tmp,"**",f"{day}-*_alpha_trace.dat"),recursive=True):
        shutil.move(f,os.path.join(dst,os.path.basename(f)))
    for f in glob.glob(os.path.join(tmp,"_log_*.txt")): shutil.move(f,os.path.join(dst,os.path.basename(f)))
    shutil.rmtree(tmp,ignore_errors=True)
if __name__=="__main__":
    ch=int(sys.argv[1]); mode=sys.argv[2]; rt=sys.argv[3]; outroot=sys.argv[4]; purge=float(sys.argv[5])
    for day in sys.argv[6:]: day_job(ch,mode,rt,day,outroot,purge)
