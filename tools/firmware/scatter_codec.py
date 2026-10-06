"""Offline encoder/model for the byte format decoded at stock 0x80001994.

Each token has a literal prefix and either zeros or a short-distance copy.
This encoder is independently tested against the original Thumb decoder. It is
not a new decoder for installation on the device.
"""
from collections import defaultdict,deque

def compress(data):
    if not data:raise ValueError('stock scatter decoder requires nonempty output')
    size=len(data);zeros=[0]*(size+1);matches=[(0,0)]*size
    for i in range(size-1,-1,-1):zeros[i]=min(255,zeros[i+1]+1) if not data[i] else 0
    positions=defaultdict(deque)
    for i in range(size-1):
        key=data[i:i+2];prior=positions[key]
        while prior and i-prior[0]>255:prior.popleft()
        best=offset=0;limit=min(257,size-i)
        for j in reversed(prior):
            n=2
            while n<limit and data[i+n]==data[j+n]:n+=1
            if n>best:best=n;offset=i-j
            if best==limit:break
        matches[i]=(best,offset);prior.append(i)
    # Minimum encoded bytes for suffixes. A token can prefix up to 254 literals
    # before its zero/copy run. Only the longest match and one offset are needed:
    # the same offset supports every shorter length at the same encoding cost.
    costs=[0]*(size+1);runs=[None]*(size+1);choices=[None]*size;runs[size]=(2,0,0)
    for i in range(size-1,-1,-1):
        best=10**9;length=offset=0
        for n in range(1,zeros[i]+1):
            cost=(1 if n<=15 else 2)+costs[i+n]
            if cost<best:best=cost;length=n;offset=0
        maximum,distance=matches[i]
        for n in range(2,maximum+1):
            cost=(2 if 3<=n<=17 else 3)+costs[i+n]
            if cost<best:best=cost;length=n;offset=distance
        choice=(best,0,length,offset)
        for literals in range(1,min(254,size-i)+1):
            run_cost,n,distance=runs[i+literals]
            cost=literals+(literals>=7)+run_cost
            if cost<choice[0]:choice=(cost,literals,n,distance)
        costs[i]=choice[0];choices[i]=choice[1:]
        runs[i]=(best,length,offset) if best<=2+costs[i] else (2+costs[i],0,0)
    out=bytearray();cursor=0
    while cursor<size:
        literals,n,distance=choices[cursor];high=n-2 if distance else n
        inline=1<=high<=15
        out.append((high<<4 if inline else 0)|(8 if distance else 0)|
                   (literals+1 if literals<=6 else 0))
        if literals>=7:out.append(literals+1)
        if not inline:out.append(high)
        out.extend(data[cursor:cursor+literals]);cursor+=literals
        if distance:out.append(distance)
        cursor+=n
    assert len(out)==costs[0]
    return bytes(out)

def expand(data,size):
    """Bounded host model; return output and consumed input bytes."""
    if size<=0:raise ValueError('nonempty destination required')
    out=bytearray();cursor=0
    def byte():
        nonlocal cursor
        if cursor>=len(data):raise ValueError('truncated input')
        value=data[cursor];cursor+=1;return value
    while len(out)<size:
        flags=byte();literals=flags&7
        if not literals:literals=byte()
        if not literals:raise ValueError('literal counter underflow')
        literals-=1;run=flags>>4
        if not run:run=byte()
        copy=bool(flags&8);run+=2 if copy else 0
        if not literals and not run:raise ValueError('token makes no progress')
        if len(out)+literals+run>size:raise ValueError('token exceeds destination')
        if cursor+literals>len(data):raise ValueError('truncated literals')
        out.extend(data[cursor:cursor+literals]);cursor+=literals
        if copy:
            distance=byte()
            if not distance or distance>len(out):raise ValueError('invalid back-reference')
            for _ in range(run):out.append(out[-distance])
        else:out.extend(bytes(run))
    return bytes(out),cursor
