#!/usr/bin/env python3
"""Bounded stock file/FAT/cache callback evidence. No device bindings."""
import json,struct
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB,CS_MODE_MCLASS
from audit_handoff_dependencies import inventory,ROOT,BIAS
from build_deployment_probe import SOURCE

TARGETS={'file_OPEN':0x800604e8,'file_READ':0x80060818,'file_WRITE':0x800624a8,'file_CLOSE':0x8005c388,
    'filesystem_init':0x80026bf0,'handle_pool_init':0x80062d68,
    'bitmap_register':0x800614b0,'volume_mount':0x80062950,
    'partition_scan':0x8006c6b8,'bitmap_initialize':0x80067868,
    'FAT_free_scan':0x80071b48,'geometry_public':0x8005e958,'geometry_driver':0x8005eb80,
    'SD_capacity':0x800685a8,'SD_write_protection':0x800687a0,
    'file_SEEK':0x8005f350,'file_INFO':0x8005f0a0,
    'rename_public':0x80060a18,'rename_driver':0x80060c48,
    'directory_find_public':0x8005d8e8,'directory_create_public':0x8005f3d0,
    'directory_find_close':0x8005d728,'directory_change':0x8005bb08,
    'path_lookup':0x800676a0,'directory_walk':0x80063368,
    'directory_create':0x8006bd30,'root_start':0x8006f940,
    'name_scratch_init':0x80074d08,'long_name_decode':0x80074af8,'file_metadata':0x800530c8,
    'cluster_allocate':0x8004ea50,'file_request':0x8006f9b8,
    'sector_split':0x80050168,'cluster_advance':0x8006bc38,
    'cluster_coalesce':0x8006c218,'cluster_sector':0x80062e58,
    'FAT_next':0x80071a70,'cache_lookup':0x80067178,
    'cache_invalidate_range':0x800501a8,'cache_flush_range':0x80050218,
    'cache_flush_sector':0x80050298,'FAT_mirror_read':0x80062d10,
    'close_flush':0x80063490,'directory_entry':0x8006f8c8,
    'block_submit':0x80053130,'volume_submit':0x80051838,
    'volume_register':0x8006b328,'error_unwind':0x80054970,'SD_dispatch':0x80068378}
WINDOWS=((0x80001848,0x80001886),(0x8004ea50,0x8004f17c),
    (0x80050168,0x80050410),(0x80051838,0x80051892),(0x80053130,0x80053154),
    (0x80054970,0x800549ac),(0x8005c388,0x8005c3de),
    (0x80060818,0x800609ac),(0x800624a8,0x80062788),
    (0x80062788,0x80062988),(0x80062d10,0x80062d62),(0x80062e58,0x80062e80),
    (0x80063490,0x800634d8),(0x80066ec0,0x80066eca),
    (0x80067068,0x800670b0),(0x80067170,0x80067572),
    (0x8006b328,0x8006b3dc),(0x8006bc38,0x8006bcf0),
    (0x8006c218,0x8006c438),(0x8006f8c8,0x8006f938),(0x8006f9b8,0x8006fa10),
    (0x80071a70,0x80071b42),(0x8006a520,0x8006a552),
    (0x8006a6c4,0x8006a6da),(0x8006ad28,0x8006ae48),
    (0x8005ef40,0x8005f0ce),(0x8005f168,0x8005f3ce),
    (0x8005ffe8,0x80060620),(0x800530c8,0x80053130),
    (0x80063368,0x80063490),(0x800670b0,0x80067170),
    (0x80067578,0x80067870),(0x8006bd30,0x8006c218),
    (0x8006f940,0x8006f9b8),(0x80074af8,0x80074d50),
    (0x80026bf0,0x80026dcc),(0x800320f8,0x800321b8),
    (0x8005e958,0x8005ec00),(0x800614b0,0x80061590),
    (0x80062950,0x80062d10),(0x80062d68,0x80062ec8),
    (0x80067868,0x80067988),(0x8006c6b8,0x8006cde0),
    (0x80071b48,0x80071c08),(0x800685a8,0x800685d0),
    (0x800687a0,0x800687c8),(0x80060a18,0x80060f20),
    (0x8005d728,0x8005dd20),(0x8005f3d0,0x8005f610),
    (0x8005bb08,0x8005bbd0))
RECORDS=(0x800a1298,0x800a12b0,0x800a12c8,0x800a12e0)

def audit():
    report=inventory(TARGETS);stock=SOURCE.read_bytes()
    report.pop('UI_mutex_slot');report.pop('constant_formations')
    needle=struct.pack('<I',0x80068379);offsets=[];p=0
    while (p:=stock.find(needle,p))!=-1:offsets.append(p);p+=1
    assert [BIAS+p for p in offsets]==[p+4 for p in RECORDS]
    table=struct.unpack_from('<33I',stock,0x800a0b28-BIAS)
    assert table[6:11]==(0x800604e9,0x8005c389,0x80060819,0x800624a9,0x8005f351)
    assert table[27]==0x8005f0a1
    assert table[32]==0x8005eb81
    assert table[14]==0x80060c49
    report.update(status='native_sector_route_attributed_completion_unbound',
        filesystem_callbacks={name:hex(table[i]) for name,i in (('OPEN',6),('CLOSE',7),('READ',8),('WRITE',9),('SEEK',10),('RENAME',14),('INFO',27),('GEOMETRY',32))},
        SD_callback_records=[dict(record=hex(p),callback_field=hex(p+4),callback='0x80068379') for p in RECORDS],
        registration=dict(entry='0x8006b328',copy_site='0x8006b3aa',descriptor_callback_offset=8,volume_callback_offset='0x240'),
        sector_request=dict(entry='0x80053130',volume=0,buffer=4,count=8,relative_sector='0x18',
            partition_field='volume+0x234',callback_site='0x8005186a BLX r1',callback_field='volume+0x240'),
        packet=dict(operation=0,unit=1,parameter=4,buffer=8,count=12,absolute_sector=16,
            close_barrier='operation 6; subcommand 4 at byte 8; other words are not meaningful'),
        facts=[
            'Native READ/WRITE use FAT chain coalescing, partial-sector cache and the registered SD callback',
            'Filesystem initializer constructs ten cache nodes with stride 0x280 and clears the native 100-slot handle pool',
            'Stock bitmap registration supplies 0x80579e60 with budget 0x80400; mount uses strict capacity admission or falls back to a FAT scan',
            'Native partition/boot parsing and FAT free-space scan now execute before capture; tested FAT32 paths do not read FSInfo hints',
            'A failed bitmap scan can leave bitmap-enabled set while volume-ready and free-count-valid remain clear',
            'The mount ignores a failed write-protection query and can still set volume-ready; it cannot by itself authorize new storage work',
            'Public partition discovery invokes device callbacks before creating a filesystem exception frame, while still holding file tokens',
            'Original outer card mount also checks application capacity/cluster policy; native FAT32-ready is not sufficient for stock acceptance',
            'Original recorder/pad directory setup now creates six folders from an empty fixture card through native find/create/close/chdir',
            'Tested same-folder native TMP-to-WAV rename rejects an existing destination and changes metadata without copying payload or allocating clusters',
            'Native rename barrier error can follow a persisted name change; public failure is not an unchanged SAFE seal result',
            'Native OPEN allocates its handle from the 100-slot pool, traverses UTF16 paths and creates/checks long filenames with exclusive-create flags 0x501',
            'Long-filename scratch must be initialized by stock 0x80074d08; the immutable locale tables already reside in MAIN',
            'Native SEEK traverses FAT clusters; INFO sets exception context without file tokens and copies length/position/slack from the handle',
            'Single aligned sector READ is converted into the partial/cache path; larger aligned reads use the direct payload path',
            'Native allocation FAT-scan branch and CLOSE update cached FAT sectors, both FAT copies and directory metadata',
            'CLOSE sets handle byte 0 to FF before directory lookup and flush; cache flush sets dirty state to zero before submission',
            'Volume submit maps driver failure through the actual filesystem setjmp/longjmp frame',
            'A later fragmented payload failure can leave earlier sectors changed while actual byte count and file position remain zero',
            'Cached FAT/payload/directory transfers use the native SD bounce buffer in the composed fixture',
            'The native SD command clears ARG after command completion; DMA modeling must retain the issued argument',
            'SD split/bounce argument advancement uses HOST+12 bit 30 to distinguish sector and byte addressing',
            'Known optimized FAT slot paths can call volume+0x240 directly; block_submit and volume_submit are not exhaustive hook boundaries',
            'The existing offline SD callback checkpoint retains all examined payload/metadata frames before filesystem error unwinding'],
        next_requirements=[
            'Connect full board/card identity and storage authorization beyond the tested native FAT32 filesystem initialization; cover other filesystem modes as needed',
            'Establish actual SD completion, CPU cache visibility and source exclusion; a MODEL permission is not a detector',
            'Cover outer card/USB transition admission before their first mutations and serialize against added I/O',
            'Keep capture startup release disabled until native storage authorization and transfer/error lifetime are established'],
        limitations=report['limitations']+[
            'Card/partition/boot/FAT/directory bytes and initial card capacity are fixture inputs; native_mount now builds geometry, caches and bitmap from them',
            'All filesystem modes/callbacks/callers, normal board/card initialization and complete card identity are not established',
            'DMA bytes, IRQ timing, source exclusion, kernel scheduling, cache effects and physical joins remain models',
            'Normal capture ELF is unchanged; capture_native_files composes it with native files/SD and a separate test-only completion probe'])
    return report

def main():
    report=audit();out=ROOT/'analysis/native_filesystem_inventory.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    stock=SOURCE.read_bytes();md=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_MCLASS)
    listing=[]
    for lo,hi in WINDOWS:
        listing.append(f'BOUND {lo:08x}..{hi:08x}')
        listing.extend(f'{a:08x} {op:10} {args}' for a,n,op,args in md.disasm_lite(stock[lo-BIAS:hi-BIAS],lo))
    (ROOT/'analysis/native_filesystem_disassembly.txt').write_text('\n'.join(listing)+'\n')
    print(json.dumps(dict(status=report['status'],targets=len(TARGETS),
        direct_references=sum(len(t['direct_references']) for t in report['targets'].values()),
        callback_records=len(RECORDS),report=str(out))))

if __name__=='__main__':main()
