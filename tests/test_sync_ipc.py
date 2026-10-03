import os
from pathlib import Path
import socket
import struct
import sys
from types import SimpleNamespace

import pygame
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]))
from system import controller
from toddlerbox.runtime.control import AppChannel,draw_receipt
from toddlerbox.ui import theme


def test_sync_hold_needs_same_keyboard_fires_once_and_release_rearms_without_shift():
    chord=controller.SyncChord()
    keys={1:{29,56},2:{31}}
    assert not chord.poll(keys,0) and not chord.poll(keys,10)
    keys[1].add(31)
    assert not chord.poll(keys,11) and not chord.poll(keys,12.99)
    assert chord.poll(keys,13)
    assert not chord.poll(keys,30)
    keys[1].remove(31)
    assert not chord.poll(keys,31)
    keys[1].add(31)
    assert not chord.poll(keys,32) and chord.poll(keys,34)


def test_parent_chord_suppresses_sync_until_release_and_keyboard_loss_cancels_hold():
    chord=controller.SyncChord();keys={1:{29,56,31,102}}
    assert not chord.poll(keys,0,parent_priority=True)
    assert not chord.poll(keys,3,parent_priority=True)
    keys[1].remove(102)
    assert not chord.poll(keys,5)
    keys.clear();assert not chord.poll(keys,6)
    keys[2]={29,56,31}
    assert not chord.poll(keys,7)
    keys.clear();assert not chord.poll(keys,20)
    keys[2]={29,56,31}
    assert not chord.poll(keys,21) and chord.poll(keys,23)


class Packets:
    def __init__(self):self.incoming=[];self.sent=[]
    def recvmsg(self,*args):
        if not self.incoming:raise BlockingIOError
        return self.incoming.pop(0)
    def sendto(self,message,address):self.sent.append((message,address))


def packet(message,uid=0,pid=10,flags=0):
    return message,[(socket.SOL_SOCKET,socket.SCM_CREDENTIALS,struct.pack('3i',pid,uid,uid))],flags,b''


def channel(clock):
    value=AppChannel.__new__(AppChannel)
    value.socket=Packets();value.clock=lambda:clock[0];value.address='/root-controller'
    value.received_at=float('-inf');value.serviced=[]
    return value


def test_app_ignores_child_forgery_truncated_packets_and_malformed_requests():
    app=channel([10]);saves=[]
    app.socket.incoming=[packet(b'sync-received',uid=1001),packet(b'sync-received',flags=socket.MSG_CTRUNC),
                         packet(b'save-current:'+b'a'*32,uid=1001),packet(b'save-current:../../bad')]
    app.service(lambda:saves.append(True))
    assert app.received_at==float('-inf') and not saves and not app.socket.sent


def test_app_receipt_and_save_are_normal_thread_callbacks_once_per_nonce():
    clock=[10];app=channel(clock);saves=[];nonce=b'a'*32
    app.socket.incoming=[packet(b'sync-received'),packet(b'save-current:'+nonce),packet(b'save-current:'+nonce)]
    def save():saves.append('durable');return True
    app.service(save)
    assert saves==['durable'] and app.received_at==10
    assert app.socket.sent==[(b'save-result:'+nonce+b':ok','/root-controller')]
    clock[0]=11;app.socket.incoming=[packet(b'sync-received')];app.service(save)
    assert app.received_at==11  # Every recognized repeat after release can show it.


def test_failed_save_is_not_acknowledged_as_success():
    app=channel([10]);nonce=b'b'*32
    app.socket.incoming=[packet(b'save-current:'+nonce)]
    def failed():raise OSError(28,'ENOSPC')
    app.service(failed)
    assert app.socket.sent[0][0]==b'save-result:'+nonce+b':failed'


@pytest.fixture
def bridge(monkeypatch):
    now=[10.0];health=Packets();control=Packets()
    monkeypatch.setattr(controller,'launcher_processes',lambda uid:{50:99})
    monkeypatch.setattr(controller.os,'close',lambda fd:None)
    monkeypatch.setattr(controller.select,'select',lambda *args:([],[],[]))
    monkeypatch.setattr(controller.time,'monotonic',lambda:now[0])
    result=controller.SyncBridge(health,control,1001)
    result.frame((50,1001,1001),b'\0toddlerbox-app-50-random',now[0])
    return result,now


def test_controller_pins_launcher_and_ignores_wrong_process_or_old_ack(bridge):
    item,now=bridge;nonce=b'a'*32;address=b'\0toddlerbox-sync-parent'
    item.request(b'save-current:'+nonce,address,now[0])
    assert item.health.sent[-1][0]==b'save-current:'+nonce
    for credentials in [(51,1001,1001),(50,2000,2000),None]:
        item.result(b'save-result:'+nonce+b':ok',credentials)
    assert not item.control.sent
    item.result(b'save-result:'+b'b'*32+b':ok',(50,1001,1001))
    assert not item.control.sent
    item.result(b'save-result:'+nonce+b':ok',(50,1001,1001))
    assert item.control.sent==[(b'save-result:'+nonce+b':ok',address)]


def test_save_request_times_out_at_five_seconds_without_blocking_supervision(bridge):
    item,now=bridge;nonce=b'a'*32;address=b'\0toddlerbox-sync-parent'
    item.request(b'save-current:'+nonce,address,now[0]);item.tick(14.99)
    assert not item.control.sent
    now[0]=15.0;item.tick(now[0])
    assert item.control.sent[-1][0]==b'save-result:'+nonce+b':timeout'
    item.result(b'save-result:'+nonce+b':ok',(50,1001,1001))
    assert len(item.control.sent)==1


def test_replaced_peer_generation_cannot_ack_an_old_request(bridge):
    item,now=bridge;nonce=b'a'*32
    item.request(b'save-current:'+nonce,b'\0toddlerbox-sync-parent',now[0])
    item.frame((50,1001,1001),b'\0toddlerbox-app-50-new',now[0])
    item.result(b'save-result:'+nonce+b':ok',(50,1001,1001))
    assert not item.control.sent


def test_every_hold_receipt_even_while_systemctl_start_pending_and_no_session_switch(bridge,monkeypatch):
    item,now=bridge;starts=[]
    def start(args,**kwargs):starts.append(args);return SimpleNamespace(poll=lambda:None)
    monkeypatch.setattr(controller.subprocess,'Popen',start)
    item.start(10);item.start(11)
    assert [m for m,a in item.health.sent]==[b'sync-received',b'sync-received']
    assert starts==[['systemctl','start','--no-block','toddlerbox-sync.service']]
    item.start(16)
    assert len(item.health.sent)==2  # Stale/frozen peer gets no promised receipt.


def test_overlay_has_real_pixels_fades_and_disappears_without_touching_input(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER','dummy')
    pygame.display.init()
    try:
        surface=pygame.Surface((1024,600));surface.fill(theme.BACKGROUND)
        before=pygame.image.tobytes(surface,'RGB');events=pygame.event.get()
        draw_receipt(surface,10,10)
        full=pygame.image.tobytes(surface,'RGB')
        assert full!=before
        home=theme.home_rect(surface.get_rect());bounds=pygame.Rect(home.left-60,home.centery-24,48,48)
        outside=surface.copy();outside.fill(theme.BACKGROUND,bounds)
        assert pygame.image.tobytes(outside,'RGB')==before
        surface.fill(theme.BACKGROUND);draw_receipt(surface,10,11.35)
        faded=pygame.image.tobytes(surface,'RGB')
        assert faded!=before and faded!=full
        surface.fill(theme.BACKGROUND);draw_receipt(surface,10,11.5)
        assert pygame.image.tobytes(surface,'RGB')==before
        assert pygame.event.get()==[]
    finally:pygame.quit()


def test_kernel_supplied_credentials_reject_unprivileged_datagram(tmp_path):
    if os.geteuid()==0:
        pytest.skip('Unprivileged sender test; privileged receive is exercised in VM')
    # Real AF_UNIX and SCM_CREDENTIALS, no mocked ancillary payload.
    endpoint=str(tmp_path/'controller.sock')
    with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as root_receiver:
        root_receiver.bind(endpoint)
        channel=AppChannel(endpoint,clock=lambda:10)
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as sender:
                sender.sendto(b'sync-received',channel.socket.getsockname())
                sender.sendto(b'save-current:'+b'a'*32,channel.socket.getsockname())
            saves=[];channel.service(lambda:saves.append(True))
            assert channel.received_at==float('-inf') and not saves
        finally:channel.close()
