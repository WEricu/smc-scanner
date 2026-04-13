#!/usr/bin/env python3
import ccxt
import pandas as pd
import requests
import os
import time
from datetime import datetime, timezone

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SYMBOLS = ["BTC/USDT:USDT","ETH/USDT:USDT","BNB/USDT:USDT","SOL/USDT:USDT",
            "XRP/USDT:USDT","DOGE/USDT:USDT","ADA/USDT:USDT",
            "TRX/USDT:USDT","AVAX/USDT:USDT","LINK/USDT:USDT",
 "XAU/USDT:USDT","XAG/USDT:USDT","AAVE/USDT:USDT","PENGU/USDT:USDT","HYPE/USDT:USDT","BCH/USDT:USDT","PEPE/USDT:USDT","SUI/USDT:USDT","RIVER/USDT:USDT"]

SL_FIXED_PCT=0.01
LEVERAGE=20
POSITION_USDT=10
TP1_RATIO=1.0
TP2_RATIO=2.0
MIN_RETURN_PCT=0.30
SWING={"1h":3,"30m":3,"15m":2,"5m":2}
exchange=ccxt.bitget({"enableRateLimit":True,"options":{"defaultType":"swap"}})

def fetch_ohlcv(symbol,timeframe,limit=200):
    raw=exchange.fetch_ohlcv(symbol,timeframe,limit=limit)
    df=pd.DataFrame(raw,columns=["ts","open","high","low","close","volume"])
    df["ts"]=pd.to_datetime(df["ts"],unit="ms")
    return df.reset_index(drop=True)

def find_swings(df,n=2):
    h,l,sh,sl=df["high"].values,df["low"].values,[],[]
    for i in range(n,len(df)-n):
        if all(h[i]>h[i-j] for j in range(1,n+1)) and all(h[i]>h[i+j] for j in range(1,n+1)):sh.append(i)
        if all(l[i]<l[i-j] for j in range(1,n+1)) and all(l[i]<l[i+j] for j in range(1,n+1)):sl.append(i)
    return sh,sl

def analyze_structure(df,n=2):
    sh_idx,sl_idx=find_swings(df,n)
    d={"direction":"neutral","choch":False,"choch_dir":None,"bos_count":0,
       "last_sh":df["high"].max(),"last_sl":df["low"].min()}
    if len(sh_idx)<2 or len(sl_idx)<2:return d
    sw=[(i,"H",df["high"].iloc[i]) for i in sh_idx]+[(i,"L",df["low"].iloc[i]) for i in sl_idx]
    sw.sort(key=lambda x:x[0])
    ph=pl=None;tr="neutral";ev=[]
    for idx,st,pr in sw:
        if st=="H":
            if ph is not None:
                if pr>ph:ev.append((idx,"CHoCH_up" if tr=="downtrend" else "BOS_up"));tr="uptrend"
                else:ev.append((idx,"CHoCH_down" if tr=="uptrend" else "BOS_down"));tr="downtrend"
            ph=pr
        else:
            if pl is not None:
                if pr<pl:ev.append((idx,"CHoCH_down" if tr=="uptrend" else "BOS_down"));tr="downtrend"
                else:ev.append((idx,"CHoCH_up" if tr=="downtrend" else "BOS_up"));tr="uptrend"
            pl=pr
    if not ev:return d
    li=ld=None
    for i in range(len(ev)-1,-1,-1):
        if "CHoCH" in ev[i][1]:li=i;ld="up" if "up" in ev[i][1] else "down";break
    bc=sum(1 for e in (ev[li+1:] if li is not None else []) if "BOS" in e[1] and (("up" in e[1])==(ld=="up")))
    return {"direction":ld or ("up" if tr=="uptrend" else "down"),"choch":li is not None,
            "choch_dir":ld,"bos_count":bc,"last_sh":df["high"].iloc[sh_idx[-1]],"last_sl":df["low"].iloc[sl_idx[-1]]}

def find_ob(df,direction):
    sub=df.tail(80).reset_index(drop=True)
    for i in range(len(sub)-4,1,-1):
        c=sub.iloc[i];nxt=sub.iloc[i+1:i+4]
        if direction=="up":
            if c["close"]<c["open"] and sum(1 for _,r in nxt.iterrows() if r["close"]>r["open"])>=2:
                return {"high":c["high"],"low":c["low"],"open":c["open"],"close":c["close"],"entry":c["low"]}
        else:
            if c["close"]>c["open"] and sum(1 for _,r in nxt.iterrows() if r["close"]<r["open"])>=2:
                return {"high":c["high"],"low":c["low"],"open":c["open"],"close":c["close"],"entry":c["high"]}
    return None

def evaluate_signal(symbol):
    try:
        d1h=fetch_ohlcv(symbol,"1h",200);time.sleep(0.25)
        d30m=fetch_ohlcv(symbol,"30m",200);time.sleep(0.25)
        d15m=fetch_ohlcv(symbol,"15m",150);time.sleep(0.25)
        d5m=fetch_ohlcv(symbol,"5m",100);time.sleep(0.25)
    except Exception as e:print(f"fetch [{symbol}]: {e}");return None
    s1h=analyze_structure(d1h,SWING["1h"]);s30m=analyze_structure(d30m,SWING["30m"])
    s15m=analyze_structure(d15m,SWING["15m"]);s5m=analyze_structure(d5m,SWING["5m"])
    price=d5m["close"].iloc[-1]
    for side in ("up","down"):
        sig=_check(side,s1h,s30m,s15m,s5m,d5m,price,symbol)
        if sig:return sig
    return None

def _check(side,s1h,s30m,s15m,s5m,d5m,price,symbol):
    if not(s1h["choch"] and s1h["choch_dir"]==side and s1h["bos_count"]>=1):return None
    ok30=s30m["choch"] and s30m["choch_dir"]==side and s30m["bos_count"]>=1
    ok15=s15m["choch"] and s15m["choch_dir"]==side and s15m["bos_count"]>=1
    if ok30 and ok15:cf="standard"
    else:return None
    if not(s5m["choch"] and s5m["choch_dir"]==side and s5m["bos_count"]>=1):return None
    ob=find_ob(d5m,side)
    if ob is None:return None
    en=ob["entry"]
    sp=SL_FIXED_PCT;sl=en*(1-sp) if side=="up" else en*(1+sp)
    rk=abs(en-sl);tp1=en+rk*TP1_RATIO if side=="up" else en-rk*TP1_RATIO;tp2=en+rk*TP2_RATIO if side=="up" else en-rk*TP2_RATIO
    return {"symbol":symbol,"direction":"LONG" if side=="up" else "SHORT","price":price,
            "entry":en,"sl":sl,"tp1":tp1,"tp2":tp2,"sl_pct":sp*100,"confluence":cf,
            "ob":ob,"structure":{"1h":s1h,"30m":s30m,"15m":s15m,"5m":s5m}}

def _tf(s,ex,lb):
    ok=s.get("choch") and s.get("choch_dir")==ex and s.get("bos_count",0)>=1
    ar="\u2191" if ex=="up" else "\u2193"
    if ok:return f"\u2705 {lb} CHoCH{ar}+BOS{ar}"
    if not s.get("choch") or s.get("direction")=="neutral":return f"\u26aa {lb} Neutral"
    return f"\u274c {lb} Unconfirmed"

def send_signal(sig):
    if not TELEGRAM_TOKEN:return
    sym=sig["symbol"].replace("/USDT:USDT","")
    side=sig["direction"];ed="up" if side=="LONG" else "down"
    ic="\U0001f7e2" if side=="LONG" else "\U0001f534"
    lb="Long" if side=="LONG" else "Short"
    sm=f"Std Fixed SL={SL_FIXED_PCT*100:.0f}%"
    ru=POSITION_USDT*sig["sl_pct"]/100*LEVERAGE
    s=sig["structure"]
    txt=(f"{ic} *{sym} {lb} Signal*\n\n"
         f"Entry (OB): {sig['entry']:.4f}\n"
         f"SL: {sig['sl']:.4f} ({sig['sl_pct']:.2f}%)\n"
         f"TP1 (1R): {sig['tp1']:.4f}\n"
         f"TP2 (2R): {sig['tp2']:.4f}\n\n"
         f"Order Block 5M: {sig['ob']['low']:.4f}-{sig['ob']['high']:.4f}\n\n"
         f"Confluence:\n{_tf(s['1h'],ed,'1H')}\n{_tf(s['30m'],ed,'30M')}\n"
         f"{_tf(s['15m'],ed,'15M')}\n{_tf(s['5m'],ed,'5M')}\n"
         f"Mode: {sm}\n\n"
         f"Leverage {LEVERAGE}x | Size {POSITION_USDT}U | Risk ~{ru:.2f}U\n"
         f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":txt,"parse_mode":"Markdown"},timeout=10)
        print(f"  {'OK' if r.ok else 'FAIL'} {sym} {side}")
    except Exception as e:print(f"  TG error: {e}")

def main():
    print(f"SMC Scanner | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    hits=0
    for sym in SYMBOLS:
        print(f"-> {sym}")
        sig=evaluate_signal(sym)
        if sig:print(f"  {sig['direction']} signal");send_signal(sig);hits+=1
        time.sleep(0.5)
    print(f"Done: {hits}/{len(SYMBOLS)}")

if __name__=="__main__":
    main()
