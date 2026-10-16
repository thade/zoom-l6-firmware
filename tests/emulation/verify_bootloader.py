#!/usr/bin/env python3
"""The bootloader's boot decision and SD system update, executed with its own
instructions from the private flash backup (docs/research/bootloader_findings.txt)
over a modelled 4 MiB flash (erase sets 0xff, programming clears bits), a
modelled A:\\L6.BIN and modelled GPIO data registers. Modelled, not executed:
the serial-flash and SD drivers, the filesystem and the RTOS locks.

Needs Reference/flash-backup/ (experiment 39); without it the suite is skipped.
Zoom's bootloader is read from there and never written anywhere else.
"""
import json,struct,sys
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
ROOT=Path(__file__).resolve().parents[2]
BACKUPS=sorted((ROOT/'Reference/flash-backup').glob('l6-flash-*.bin'))
STOCK=ROOT/'Reference/L6_v1.10_E/L6.BIN'
BOOT_SHA='21bad1390601e5833eec2b892f064d28f40494d5c747bb21023732cb44c1e00b'   # BOOT region of the backup
BASE,LEN=0x81d8e000,0x3bc00                 # load address and length from the IVT's boot data
REGS=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3]
RETURN,STACK=0x20200000,0x20240000
KEYS=0x81f481c0+0x54                        # active-low key word: bit 1 PLAY/STOP
GPIO={1:0x401b8000,2:0x401bc000,3:0x401c0000,4:0x401c4000,5:0x400c0000}
PLAY_PORT,PLAY_PIN=2,25
STATE=0x81e896c0                            # update: +0x54 file, +0x60 component offset, +0x68 length
SAMPLE_KEYS,DECIDE,UPDATE_MODE,START_MAIN=0x81d940f0,0x81d985f0,0x81d98470,0x81d8fc28
CHECK,SYSTEM=0x81d900e8,0x81d99030
FLASH_READ,FLASH_ERASE,FLASH_PROGRAM=0x81d90d08,0x81d908f0,0x81d90da0
F_LSEEK,F_READ,TAKE,GIVE,DELAY=0x81da8730,0x81da75e0,0x81db5238,0x81db4cc0,0x81db4980
REGIONS=(0x65000,0x3fa000)                  # MAIN + PANEL + AUDIOGUIDE, the system update's span
MARKER=(0x3f2000,0x3fa000)                  # the block holding the update-complete marker

class PowerLoss(Exception):pass

class Bootloader:
    def __init__(self,backup,flash,package=None):
        self.uc=uc=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        uc.mem_map(0x81d00000,0x300000);uc.mem_map(0x20000000,0x300000);uc.mem_map(0x40000000,0x400000)
        uc.mem_write(BASE,backup[:LEN])
        self.flash=bytearray(flash);self.package=package;self.pos=0;self.ops=[];self.cut_after=None
        self.hooks={TAKE:lambda a:1,GIVE:lambda a:1,DELAY:lambda a:0,FLASH_READ:self.read,
                    FLASH_ERASE:self.erase,FLASH_PROGRAM:self.program,F_LSEEK:self.lseek,F_READ:self.fread}
        uc.hook_add(UC_HOOK_CODE,self._hook)
        self.invoke(0x81d8f830,[0x81dc9b20,0x81e89000,0x3a0])   # the scatter table's initialized data
        for base in GPIO.values():self.w32(base,0xffffffff)      # every input high: nothing pressed
        uc.mem_write(0x81ec2d74+0xc,b'\x01')                      # the key sampler's ADC value is ready
    def _hook(self,uc,address,size,_):
        if address==RETURN:self.reached=True;uc.emu_stop();return
        h=self.hooks.get(address)
        if h is None:return
        args=[uc.reg_read(r) for r in REGS]
        try:r=h(args)
        except PowerLoss:self.lost=True;uc.emu_stop();return
        if r is not None:uc.reg_write(UC_ARM_REG_R0,r&0xffffffff)
        uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    def invoke(self,addr,args):
        uc=self.uc;uc.reg_write(UC_ARM_REG_SP,STACK);uc.reg_write(UC_ARM_REG_LR,RETURN|1)
        for r,v in zip(REGS,args):uc.reg_write(r,v)
        self.reached=self.lost=False
        uc.emu_start(addr|1,RETURN+2,count=300_000_000)
        if self.lost:return None
        assert self.reached,f'stopped at {uc.reg_read(UC_ARM_REG_PC):#x}'
        return uc.reg_read(UC_ARM_REG_R0)
    def w32(self,a,v):self.uc.mem_write(a,struct.pack('<I',v))
    def r32(self,a):return struct.unpack('<I',self.uc.mem_read(a,4))[0]
    def read(self,a):self.uc.mem_write(a[1],bytes(self.flash[a[0]:a[0]+a[2]]));return 0
    def _op(self,*op):
        self.ops.append(op)
        if self.cut_after is not None and len(self.ops)>self.cut_after:raise PowerLoss
    def erase(self,a):self._op('erase',a[0],a[1]);self.flash[a[0]:a[0]+a[1]]=b'\xff'*a[1];return 0
    def program(self,a):
        self._op('program',a[0],a[2]);data=self.uc.mem_read(a[1],a[2])
        self.flash[a[0]:a[0]+a[2]]=bytes(x&y for x,y in zip(self.flash[a[0]:a[0]+a[2]],data));return 0
    def lseek(self,a):self.pos=a[1];return 0
    def fread(self,a):
        data=self.package[self.pos:self.pos+a[2]];self.pos+=len(data)
        self.uc.mem_write(a[1],data);self.w32(a[3],len(data));return 0
    def press_play(self,pressed):
        port=GPIO[PLAY_PORT];v=self.r32(port)
        self.w32(port,v&~(1<<PLAY_PIN) if pressed else v|(1<<PLAY_PIN))
    def boot(self):
        """Power-on: sample the keys from the GPIO pins, then decide."""
        self.w32(KEYS,0);self.invoke(SAMPLE_KEYS,[]);seen=[]
        self.hooks[UPDATE_MODE]=lambda a:seen.append('update') or 0
        self.hooks[START_MAIN]=lambda a:seen.append('main') or 0
        self.invoke(DECIDE,[]);del self.hooks[UPDATE_MODE],self.hooks[START_MAIN]
        assert len(seen)==1;return seen[0]
    def check(self):return self.invoke(CHECK,[1,1,0x100,0x395100])
    def system_update(self):
        self.ops=[];self.pos=0
        self.w32(STATE+0x54,1);self.w32(STATE+0x60,0x100);self.w32(STATE+0x68,0x395100)
        return self.invoke(SYSTEM,[])

def main():
    if not BACKUPS:
        print(json.dumps(dict(passed=True,groups=0,skipped='no flash backup in Reference/flash-backup (experiment 39)')));return
    import hashlib
    from build_deployment_probe import STOCK_SHA,digest
    from build_recovery_hang_probe import candidate
    from build_master_trial import trial
    backup=BACKUPS[-1].read_bytes();assert hashlib.sha256(backup[:0x65000]).hexdigest()==BOOT_SHA,'unexpected bootloader'
    stock=STOCK.read_bytes();assert digest(stock)==STOCK_SHA
    hang=candidate(stock)[0];release=trial('release')[0]
    span=lambda f:bytes(f[REGIONS[0]:REGIONS[1]])
    cases=[]
    def passed(case,**d):cases.append(dict(case=case,**d))

    # Keys come from the GPIO pins; PLAY/STOP held or a missing marker enters
    # update mode before MAIN is loaded; otherwise MAIN starts.
    b=Bootloader(backup,backup);seen={}
    seen['idle']=b.boot()
    b.press_play(True);seen['play_stop']=b.boot();assert b.r32(KEYS)&2==0;b.press_play(False)
    no_marker=bytearray(backup);no_marker[MARKER[0]:MARKER[1]]=b'\xff'*(MARKER[1]-MARKER[0])
    seen['marker_erased']=Bootloader(backup,no_marker).boot()
    bad_version=bytearray(backup);bad_version[0x3f9ffc]=0x01
    seen['marker_bad_version']=Bootloader(backup,bad_version).boot()
    assert seen==dict(idle='main',play_stop='update',marker_erased='update',marker_bad_version='update'),seen
    passed('play_stop_from_its_gpio_pin_or_a_missing_marker_enters_update_mode_before_main',
           play_stop=f'GPIO{PLAY_PORT}_IO{PLAY_PIN}',outcomes=seen)

    # The package check accepts stock and our images and rejects damage
    # before anything is erased.
    verdicts={name:Bootloader(backup,backup,p).check() for name,p in
              (('stock',stock),('release_0.1.0',release),('experiment_18_hang',hang))}
    flipped=bytearray(release);flipped[0x200000]^=1
    b=Bootloader(backup,backup,bytes(flipped));verdicts['one_bit_flipped']=b.check()
    verdicts['flipped_update']=b.system_update();erased=len(b.ops)
    verdicts['truncated']=Bootloader(backup,backup,release[:0x300000]).check()
    assert verdicts=={'stock':0,'release_0.1.0':0,'experiment_18_hang':0,'one_bit_flipped':1,'flipped_update':6,'truncated':1},verdicts
    assert erased==0 and b.flash==bytearray(backup)
    passed('the_package_check_accepts_our_images_and_rejects_damage_before_erasing',verdicts=verdicts)

    # Installing the hang image: the marker block is erased first and written
    # last; BOOT and the flash beyond AUDIOGUIDE are untouched. MAIN would
    # start (and hang); PLAY/STOP still reaches update mode, and stock
    # restores the flash.
    b=Bootloader(backup,backup,hang);assert b.system_update()==0;ops=b.ops
    assert ops[0]==('erase',MARKER[0],MARKER[1]-MARKER[0]) and ops[-1][0]=='program' and ops[-1][1]<=0x3f9fc0<ops[-1][1]+ops[-1][2]
    assert span(b.flash)==hang[0x200:0x395200] and bytes(b.flash[:REGIONS[0]])==backup[:REGIONS[0]] and bytes(b.flash[REGIONS[1]:])==backup[REGIONS[1]:]
    after={'idle':b.boot()};b.press_play(True);after['play_stop']=b.boot();b.press_play(False)
    b.package=stock;assert b.system_update()==0 and span(b.flash)==stock[0x200:0x395200];after['restored']=b.boot()
    assert after==dict(idle='main',play_stop='update',restored='main'),after
    passed('the_update_installs_the_hang_image_and_play_stop_restores_stock',operations=len(ops),
           first=list(ops[0][:2]),last=list(ops[-1][:2]),outcomes=after)

    # Power lost at any point after the first erase leaves the mixer in update
    # mode at the next power-on, and a stock update then restores it.
    outcomes=[]
    for n in (0,1,len(ops)//4,115,len(ops)*3//4,len(ops)-1):
        b=Bootloader(backup,backup,hang);b.cut_after=n;assert b.system_update() is None
        nxt=b.boot();b.cut_after=None;b.package=stock;restored=b.system_update()==0 and span(b.flash)==stock[0x200:0x395200]
        outcomes.append(dict(lost_before=list(ops[n][:2]),next_boot=nxt,restored=restored,then=b.boot()))
        assert nxt==('main' if n==0 else 'update') and restored and outcomes[-1]['then']=='main',outcomes[-1]
    passed('power_loss_during_an_update_leaves_update_mode_and_stock_restores',cuts=outcomes)

    result=dict(passed=True,groups=len(cases),results=cases,
                limitations=['Flash, SD, filesystem and RTOS locks are modelled; the bootloader code between them is executed.',
                             'The LED states and the bootloader-update path are not covered.'])
    (ROOT/'analysis/bootloader_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(cases))))
if __name__=='__main__':main()
