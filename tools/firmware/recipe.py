#!/usr/bin/env python3
"""Release recipes: what turns Zoom's stock L6 v1.10 L6.BIN into a release
image, without any of Zoom's bytes. No device access.

A release image differs from stock in four ways (plan_simple_capture.py
reuse_packing, build_simple_trial.py assemble):
- the stock DSP record (a plain scatter copy) is stored compressed in its own
  span, with our packed code in the space this frees, the rest 0xff;
- short patches and the scatter-table tail elsewhere in MAIN;
- the additive checksum.

The compressed DSP stream is a token stream whose literal bytes are the stock
DSP bytes in order. The recipe keeps only the tokens (the skeleton) and
reinserts the literals from the user's own stock file, so neither the
compressor nor any stock data ships. Patch bytes that equal stock bytes at
another place (the scatter records the new table moves) become copy
operations from the user's file. Our packed code is our compiler's output;
like any Thumb code it shares short instruction sequences with stock code
(the few displaced stock instructions each hook replays, common prologues),
which stock_bytes() therefore does not audit. The browser patcher (patcher/patcher.js)
executes the same steps as rebuild() below, then refuses any result that does
not hash to the recipe's published image hash.
"""
import base64,hashlib,struct
from capture_jump_patches import SCATTER
from build_deployment_probe import CHECKSUM_OFFSET,STOCK_SHA

FORMAT=1
BIAS=0x80000e00
MIN_COPY=8          # stock-equal runs this long or longer become copies

def b64(data):return base64.b64encode(data).decode()
def unb64(text):return base64.b64decode(text)
def sha(data):return hashlib.sha256(data).hexdigest()

def strip(packed,size):
    """The skeleton: the packed stream without its literal bytes."""
    out=bytearray();cursor=produced=0
    while produced<size:
        flags=packed[cursor];out.append(flags);cursor+=1;literals=flags&7
        if not literals:literals=packed[cursor];out.append(literals);cursor+=1
        literals-=1;run=flags>>4
        if not run:run=packed[cursor];out.append(run);cursor+=1
        copy=bool(flags&8)
        cursor+=literals;produced+=literals
        if copy:out.append(packed[cursor]);cursor+=1;run+=2
        produced+=run
    if cursor!=len(packed):raise ValueError('packed stream longer than its output')
    return bytes(out)

def clothe(skeleton,plain):
    """The packed stream again: the skeleton with plain's literals put back."""
    out=bytearray();c=p=0
    while p<len(plain):
        flags=skeleton[c];out.append(flags);c+=1;literals=flags&7
        if not literals:literals=skeleton[c];out.append(literals);c+=1
        literals-=1;run=flags>>4
        if not run:run=skeleton[c];out.append(run);c+=1
        copy=bool(flags&8)
        out+=plain[p:p+literals];p+=literals
        if copy:out.append(skeleton[c]);c+=1;run+=2
        p+=run
    if c!=len(skeleton):raise ValueError('skeleton longer than its output')
    return bytes(out)

def operations(stock,image,lo,hi):
    """Bytes outside the span (and the checksum) that differ from stock, as
    put and copy operations; a copy takes stock bytes from another offset."""
    ops=[];i=0x200
    while i<len(image):
        if lo<=i<hi or CHECKSUM_OFFSET<=i<CHECKSUM_OFFSET+4 or image[i]==stock[i]:i+=1;continue
        j=i
        while j<len(image) and image[j]!=stock[j] and not lo<=j<hi:j+=1
        run=image[i:j];k=0;put=bytearray()
        while k<len(run):
            src=stock.find(run[k:k+MIN_COPY]) if len(run)-k>=MIN_COPY else -1
            if src<0:put.append(run[k]);k+=1;continue
            n=MIN_COPY
            while k+n<len(run) and stock.find(run[k:k+n+1])>=0:n+=1
            src=stock.find(run[k:k+n])
            if put:ops.append(['put',i+k-len(put),b64(bytes(put))]);put=bytearray()
            ops.append(['copy',i+k,src,n]);k+=n
        if put:ops.append(['put',i+k-len(put),b64(bytes(put))])
        i=j
    return ops

def make(stock,image,pack,version):
    """The recipe for image, checked by rebuilding it from stock."""
    if sha(stock)!=STOCK_SHA:raise ValueError('not the stock L6 v1.10 image')
    source,_,length,_=SCATTER;lo=source-BIAS;hi=lo+length
    dsp=stock[lo:hi]
    if pack['packed_dsp']!=image[lo:lo+len(pack['packed_dsp'])]:raise ValueError('span does not start with the packed DSP record')
    at=pack['code_source']-source
    if pack['packed_code']!=image[lo+at:lo+at+len(pack['packed_code'])]:raise ValueError('packed code not where planned')
    recipe=dict(format=FORMAT,version=version,stock_sha256=STOCK_SHA,image_sha256=sha(image),image_bytes=len(image),
                checksum=dict(offset=CHECKSUM_OFFSET,sum_from=0x200),
                span=dict(offset=lo,length=length,fill=0xff,literals_from=lo,skeleton=b64(strip(pack['packed_dsp'],len(dsp))),
                          code_at=at,code=b64(pack['packed_code'])),
                ops=operations(stock,image,lo,hi))
    if rebuild(stock,recipe)!=image:raise ValueError('recipe does not rebuild the image')
    return recipe

def rebuild(stock,recipe):
    """Reference implementation of the browser patcher."""
    if recipe['format']!=FORMAT or sha(stock)!=recipe['stock_sha256']:raise ValueError('wrong recipe or stock image')
    s=recipe['span'];img=bytearray(stock);lo=s['offset']
    span=bytearray([s['fill']])*s['length']
    packed=clothe(unb64(s['skeleton']),stock[s['literals_from']:s['literals_from']+s['length']])
    code=unb64(s['code']);span[:len(packed)]=packed;span[s['code_at']:s['code_at']+len(code)]=code
    img[lo:lo+s['length']]=span
    for op in recipe['ops']:
        if op[0]=='put':data=unb64(op[2]);img[op[1]:op[1]+len(data)]=data
        else:img[op[1]:op[1]+op[3]]=stock[op[2]:op[2]+op[3]]
    c=recipe['checksum'];struct.pack_into('>I',img,c['offset'],sum(img[c['sum_from']:])&0xffffffff)
    return bytes(img)

def stock_bytes(stock,recipe,window=MIN_COPY):
    """Audit: windows of the skeleton and the put bytes that also occur in the
    stock image (the packed code is our compiler's output, whose common
    instruction sequences can coincide with stock code)."""
    shipped=[unb64(recipe['span']['skeleton'])]+[unb64(op[2]) for op in recipe['ops'] if op[0]=='put']
    return sum(1 for blob in shipped for k in range(len(blob)-window+1) if stock.find(blob[k:k+window])>=0)
