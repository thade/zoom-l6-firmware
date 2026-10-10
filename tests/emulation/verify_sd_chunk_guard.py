#!/usr/bin/env python3
"""Per-chunk lifetime checkpoint on original SD paths; no device access.

The exact positive join, prior source exclusion, DMA/cache/NVIC effects and
kernel scheduling are explicit models. This suite cannot authorize deployment.
"""
import hashlib
import json
import struct
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
from unicorn import arm_const as A
from verify_sd_transfer_probe import Probe, ELF, BOUNCE
from verify_sd_transfer_lifetime import BUFFER, EVENT, HOST
from verify_pad_protocol import ROOT, IMAGE, REGS
from verify_firmware_workflow import put32
from verify_storage_readiness import word
from verify_scheduling_boundaries import stop
from sd_registers import DMA_ADDRESS, BLOCKS, PRESENT, SYSTEM

MODEL = 0x2102b900
TASK = 0x808e291c
FIELDS = 'active code address bytes raw task completed checks'.split()

def chunk(r):
    return dict(zip(FIELDS, struct.unpack('<8I', r.m.uc.mem_read(r.syms['sdp_chunk_state'], 32))))

class Chunk(Probe):
    def __init__(self, advance=False):
        super().__init__()
        self.advance = advance
        self.chunk_calls = []
        self.dma_stores = []
        self.hold_sequence = None
        self.chunk_reply = 0
        self.data_chunks = 0
        self.missing_tc = None
        self.data_present = 0
        self.after_provider = None
        put32(self.m, TASK, 0x2103b000)
        put32(self.m, self.syms['sdp_chunk_finish_port'], MODEL | 1)
        self.m.hooks[MODEL] = self.finish_chunk
        self.m.uc.hook_add(UC_HOOK_MEM_WRITE,
            lambda u,k,a,n,v,s: self.dma_stores.append(v), begin=DMA_ADDRESS, end=DMA_ADDRESS)

    def deliver(self, args):
        start = word(self.m, DMA_ADDRESS)
        block = word(self.m, BLOCKS)
        result = super().deliver(args)
        if args[1] == 0x185:
            self.data_chunks += 1
            put32(self.m, PRESENT, self.data_present)
            if self.advance:
                put32(self.m, DMA_ADDRESS, start + (block & 0xffff) * (block >> 16))
            if self.missing_tc == self.data_chunks:
                # Explicit software-only completion, with no current raw TC.
                put32(self.m, 0x402c0030, 0)
                put32(self.m, EVENT + 8, 4)
                return 0
        return result

    def finish_chunk(self, args):
        s = chunk(self)
        assert self.held and self.state()['active'] and not self.state()['finished']
        assert not self.state()['failed'] and s['active'] and s['raw'] & 2
        assert args[:4] == [0, EVENT, s['address'], s['bytes']]
        assert word(self.m, TASK) == s['task']
        assert self.m.uc.reg_read(A.UC_ARM_REG_SP) < self.waits[-1]['sp']
        self.chunk_calls.append(dict(sample=s, args=args[:4], copies=list(self.copies),
            stores=list(self.dma_stores), sp=self.m.uc.reg_read(A.UC_ARM_REG_SP)))
        if self.after_provider:
            self.after_provider(self)
        if self.hold_sequence == s['completed'] + 1:
            stop(self.m)
            return self.chunk_reply
        return 1 # MODEL: this physical chunk and its original span have joined.

def retained(r):
    assert r.held and r.state()['active'] and not r.state()['finished']
    assert chunk(r)['active'] and r.waits[-1]['mask'] == 0x185

def main():
    checks = []
    def passed(case, **kw):
        checks.append(dict(case=case, passed=True, **kw))

    normal = []
    for op in (2, 3):
        for n, offset in ((1,0), (2,0), (2,4), (2,1), (9,1), (9,0)):
            old = Probe(); old_status = old.request(op, n, offset)
            r = Chunk(); status = r.request(op, n, offset)
            assert status == old_status == 0 and not r.held
            assert bytes(r.m.uc.mem_read(BUFFER, 0x4000)) == bytes(old.m.uc.mem_read(BUFFER, 0x4000))
            assert r.native_commands == old.native_commands
            assert [w['mask'] for w in r.waits] == [w['mask'] for w in old.waits]
            assert chunk(r)['completed'] == len(r.chunk_calls)
            assert sum(c['sample']['bytes'] for c in r.chunk_calls) == n * 512
            assert not r.joins and not r.state()['failed']
            normal.append(dict(op=op, blocks=n, offset=offset, chunks=len(r.chunk_calls)))
    passed('positive_MODEL_join_preserves_native_direct_bounce_read_write_payloads_commands_and_waits', cases=normal)

    for op in (2, 3):
        for reply in (0, 2, 0xffffffce):
            r = Chunk(); r.hold_sequence = 1; r.chunk_reply = reply
            r.request(op, 2); retained(r)
            assert len(r.dma_stores) == 1 and len(r.native_commands) == 1
            assert not r.copies and chunk(r)['completed'] == 0
            assert not r.state()['failed'] and not r.joins
            r.hold_sequence = None
            assert r.resume() == 0 and not r.held and chunk(r)['completed'] == 1
    passed('direct_read_and_write_wait_frames_remain_live_until_exact_JOINED_one', logical_cases=6)

    for op in (2, 3):
        r = Chunk(advance=True); r.hold_sequence = 1
        r.request(op, 9, 1); retained(r)
        assert r.chunk_calls[-1]['args'][2:] == [BOUNCE, 4096]
        assert word(r.m, DMA_ADDRESS) == BOUNCE + 4096
        assert len(r.dma_stores) == 1
        assert len(r.copies) == (0 if op == 2 else 1)
        r.hold_sequence = 2
        r.resume(); retained(r)
        assert chunk(r)['completed'] == 1 and len(r.dma_stores) == 2
        assert r.chunk_calls[-1]['args'][2:] == [BOUNCE, 512]
        assert len(r.copies) == (1 if op == 2 else 2)
        r.hold_sequence = None
        assert r.resume() == 0 and not r.held and chunk(r)['completed'] == 2
        assert len(r.copies) == 2
    passed('each_unaligned_nine_block_chunk_joins_before_read_copy_or_next_bounce_refill',
           original_spans=[4096,512], advanced_DS_ADDR_does_not_change_owned_start=True)

    for op in (2, 3):
        r = Chunk(); r.missing_tc = 2; r.pending = True
        r.request(op, 9, 1); retained(r)
        assert r.state()['failed'] and r.state()['raw'] & 2
        assert chunk(r)['completed'] == 1 and not chunk(r)['raw'] & 2
        assert len(r.chunk_calls) == 1 and len(r.joins) == 1
        assert len(r.copies) == (1 if op == 2 else 2)
        assert r.resume() != 0 and not r.held
        assert len(r.chunk_calls) == 1
    passed('earlier_chunk_TC_plus_software_success_cannot_release_a_later_chunk')

    for op in (2, 3):
        for fault in ('hidden_error', 'timeout'):
            r = Chunk(); r.fault = (0x185, fault); r.pending = True
            r.request(op, 1); retained(r)
            assert r.state()['failed'] and not r.chunk_calls
            assert len(r.copies) == (0 if op == 2 else 1)
            assert r.resume() != 0 and not r.held and not r.chunk_calls
    passed('raw_TC_plus_error_and_timeout_never_reach_successful_chunk_publication', logical_cases=4)

    for bit in (1, 0x80, 0x100):
        r = Chunk(); deliver = r.m.hooks[0x2102bd04]
        def mixed(args, deliver=deliver, bit=bit):
            result = deliver(args)
            if args[1] == 0x185:
                put32(r.m, EVENT + 8, word(r.m, EVENT + 8) | bit)
            return result
        r.m.hooks[0x2102bd04] = mixed; r.pending = True
        r.request(2, 1); retained(r)
        assert r.state()['failed'] and not r.chunk_calls and not r.copies
        assert r.resume() != 0 and not r.held
    passed('mixed_software_wakeup_and_error_flags_cannot_override_chunk_failure', logical_cases=3)

    for bits, register in ((0x100,PRESENT), (0x200,PRESENT), (0x4000000,SYSTEM)):
        r = Chunk()
        if register == PRESENT:
            r.data_present = bits
        else:
            previous = r.m.hooks[0x2102bd04]
            def reset(args, previous=previous):
                result = previous(args)
                if args[1] == 0x185:
                    put32(r.m, SYSTEM, bits)
                return result
            r.m.hooks[0x2102bd04] = reset
        r.m.hooks[0x80032250] = lambda args: stop(r.m)
        r.request(2, 1); retained(r)
        assert not r.chunk_calls and not r.copies and not r.state()['failed']
        put32(r.m, register, 0)
        r.m.hooks[0x80032250] = lambda args: 0
        assert r.resume() == 0 and not r.held
    passed('visible_host_read_write_activity_or_reset_prevents_join_even_with_successful_TC', logical_cases=3)

    for op in (2, 3):
        r = Chunk(); r.data_present = 6 # DAT0 low, CDIHB/DLA, host RTA/WTA clear.
        assert r.request(op, 1) == 0 and not r.held and len(r.chunk_calls) == 1
        assert not r.state()['failed'] and not r.joins
    passed('trailing_card_busy_does_not_replace_or_veto_explicit_MODEL_host_memory_join')

    for change in ('read_activity', 'reset', 'error', 'event', 'task'):
        r = Chunk(); r.pending = True
        def mutate(r, change=change):
            r.after_provider = None
            if change == 'read_activity': put32(r.m, PRESENT, 0x200)
            elif change == 'reset': put32(r.m, SYSTEM, 0x4000000)
            elif change == 'error': r.seed(errors=0x100000)
            elif change == 'event': put32(r.m, HOST + 4, EVENT + 0x100)
            else: put32(r.m, TASK, 0x2103b100)
        r.after_provider = mutate
        if change in ('read_activity','reset'):
            r.m.hooks[0x80032250] = lambda args: stop(r.m)
        r.request(2, 1); retained(r)
        assert not r.copies and chunk(r)['completed'] == 0
        if change in ('read_activity','reset'):
            assert not r.state()['failed']
            put32(r.m, PRESENT, 0); put32(r.m, SYSTEM, 0)
            r.m.hooks[0x80032250] = lambda args: 0
            assert r.resume() == 0
        else:
            assert r.state()['failed'] and r.joins
            assert r.resume() != 0
        assert not r.held
    passed('positive_provider_cannot_override_late_activity_reset_error_or_changed_owner_event', logical_cases=5)

    for field in ('event', 'mask', 'task'):
        r = Chunk(); r.pending = True
        def wrong_wait(uc, pc, n, user, field=field):
            if uc.reg_read(REGS[1]) == 0x185:
                if field == 'event': uc.reg_write(REGS[0], EVENT + 0x100)
                elif field == 'mask': uc.reg_write(REGS[1], 4)
                else: put32(r.m, TASK, 0x2103b100)
        r.m.uc.hook_add(UC_HOOK_CODE, wrong_wait, begin=0x800328c0, end=0x800328c0)
        r.request(2, 1); retained(r)
        assert r.state()['failed'] and not r.chunk_calls and not r.copies
        assert r.resume() != 0 and not r.held
    passed('exact_native_data_wait_sites_reject_wrong_event_mask_or_task_before_wait_delegation', logical_cases=3)

    for field in ('dma', 'count', 'address'):
        r = Chunk(); r.pending = True
        def malformed(uc, pc, n, user, field=field):
            request = uc.reg_read(REGS[0])
            if uc.mem_read(request,1)[0] in (22,23,32,33):
                if field == 'dma': put32(r.m, request + 20, 0)
                elif field == 'count': put32(r.m, request + 16, 0x10001)
                else: put32(r.m, DMA_ADDRESS, BUFFER + 0x6000)
        r.m.uc.hook_add(UC_HOOK_CODE, malformed, begin=0x8006a348, end=0x8006a348)
        r.request(2, 2)
        assert r.held and r.state()['failed'] and not r.native_commands and not r.chunk_calls
        assert not r.copies and r.joins
        assert r.resume() != 0 and not r.held
    passed('unsupported_DMA_shape_count_or_span_is_rejected_before_command_submission', logical_cases=3)

    r = Chunk(); r.pending = True; r.held = True
    r.seed(active=1, unit=0, event=EVENT, buffer=BUFFER, bytes=512)
    address = 0x2103ffff
    r.m.uc.mem_write(address, bytes([28]))
    reads = []
    r.m.uc.hook_add(UC_HOOK_MEM_READ, lambda u,k,a,n,v,s: reads.append((a,n)),
                   begin=address, end=address+32)
    r.m.invoke(r.syms['sdp_command'], [address,0])
    assert r.state()['failed'] and r.joins and not r.native_commands and not r.chunk_calls
    assert reads and all(a==address and n==1 for a,n in reads)
    assert r.resume() == 11
    passed('unsupported_auxiliary_command_is_held_without_reading_beyond_its_opcode_byte')

    from verify_sd_cache_contract import CacheRead
    r = CacheRead(advance_dma=True)
    put32(r.m, r.syms['sdp_chunk_finish_port'], MODEL | 1)
    held = True
    def cache_join(args):
        assert args[:4] == [0, EVENT, BUFFER, 1024]
        assert not r.invalidate and bytes(r.m.uc.mem_read(BUFFER,1024)) == b'\xa5' * 1024
        if held: return stop(r.m)
        return 1
    r.m.hooks[MODEL] = cache_join
    r.request(); retained(r)
    assert not r.invalidate and not r.copies
    held = False
    assert r.resume() == 0 and r.invalidate == list(range(BUFFER,BUFFER+1024,32))
    passed('post_read_cache_invalidation_occurs_after_chunk_join_using_original_advanced_DMA_start')

    from verify_capture_io_lifetime import CaptureSd
    class CaptureChunk(CaptureSd):
        def __init__(self):
            super().__init__()
            self.chunk_names = []; self.hold_name = None
            put32(self.m, self.syms['sdp_chunk_finish_port'], MODEL | 1)
            self.m.hooks[MODEL] = self.chunk_model
        def chunk_model(self, args):
            assert self.owner() and self.probe()['active'] and chunk(self)['active']
            assert args[:4] == [0, EVENT, BOUNCE, 512]
            self.chunk_names.append(self.current_name)
            if self.hold_name == self.current_name:
                self.stalled = True
                return stop(self.m)
            return 1
    r = CaptureChunk(); r.running()
    for _ in range(10): r.audio_call(); r.tick()
    r.stop_recording(); r.completed_extra()
    assert {'initial_header','audio','final_header','read_header','read_audio'} <= set(r.chunk_names)
    assert not r.unit_held and not r.unsafe_close
    passed('unchanged_capture_ELF_checks_payload_headers_and_readback_at_native_chunk_boundary',
           sector_routing_and_logical_files_are_models=True)

    for name in ('initial_header', 'audio', 'final_header', 'read_audio'):
        r = CaptureChunk()
        if name == 'initial_header':
            r.hold_name = name; assert r.boot(release=True) == 0
        else:
            r.running()
            for _ in range(3): r.audio_call(); r.tick()
            r.hold_name = name
            if name != 'audio': r.stop_recording()
        for _ in range(32):
            if name == 'audio': r.audio_call()
            r.tick()
            if r.stalled: break
        r.retained()
        assert chunk(r)['active'] and not r.probe()['failed']
        before = list(r.native); frame = r.frame()
        r.request_cancel()
        assert r.worker_busy() == 11 and r.frame() == frame and r.native == before
        r.hold_name = None; r.resume_io(); r.stop_after_fault()
        assert not r.unsafe_close
    passed('nominal_header_payload_finalize_and_readback_hold_file_frames_and_cancel_until_chunk_join',
           logical_cases=4, physical_join_is_MODEL=True)

    r = Chunk(); r.origin = 'previous physical transfer (deliberately false MODEL provider)'
    assert r.request(2,2) == 0 and not r.state()['failed']
    passed('negative_control_false_join_provider_can_still_accept_a_late_prior_origin_TC',
           physical_source_exclusion_not_established=True)

    report = dict(passed=True, groups=len(checks), results=checks,
        firmware_sha256=hashlib.sha256(IMAGE).hexdigest(),
        fixture_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(), device_access=False,
        limitations=['Exact positive chunk join and prior source exclusion remain MODEL providers.',
            'Native original driver, command, data wait, IRQ and event predicate execute on one CPU.',
            'Host activity/reset/cache/NVIC effects, RTOS schedule and card persistence are not physical proofs.',
            'Scope is the four traced unit-zero DMA block data-wait sites; alternate callers/modes remain excluded.',
            'New checkpoint is opt-in test-only; no production firmware image or device setting changes.'])
    out = ROOT / 'analysis/sd_chunk_guard_verification.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,groups=len(checks),report=str(out))))

if __name__ == '__main__': main()
