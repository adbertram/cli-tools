"""Multipart output and saved-turn hydration regressions from observed DOM shape."""
from types import SimpleNamespace

import pytest

from muse_chat_cli import client as module
from muse_chat_cli.client import MuseChatClient

USER = {'role':'user','text':'Check the device and schedule','dom_index':1,'message_id':'saved-user','turn_id':'saved-user'}
PROSE = {'role':'assistant','text':'Access verified.\n\nHistory read succeeded.','dom_index':2,'message_id':'prose','turn_id':'one-response'}
CARD = {'role':'assistant','text':'Daily check\n\nScheduled task\n\nChecks at the agreed time.','dom_index':3,'message_id':'card','turn_id':'one-response'}


def state(*rows, working=False, typing=False):
    return {'messages':list(rows),'working':working,'typing':typing,'approvals':[]}


class Page:
    url = 'https://muse.ai/thread/282cc7b4-3813-4ed2-84df-bca90531113b'
    def __init__(self, snapshots):self.snapshots=list(snapshots);self.clock=0.;self.reads=0
    def evaluate(self, _):
        self.reads+=1
        if len(self.snapshots)>1:return self.snapshots.pop(0)
        return self.snapshots[0]
    def wait_for_timeout(self, ms):self.clock+=ms/1000


def clock(monkeypatch,page):
    monkeypatch.setattr(module,'RESPONSE_SETTLE_SECONDS',1.)
    monkeypatch.setattr(module.time,'monotonic',lambda:page.clock)


def test_card_first_then_prose_hydration_does_not_complete_on_card(monkeypatch):
    page=Page([state(USER,CARD),state(USER,PROSE,CARD)])
    clock(monkeypatch,page)
    result=MuseChatClient._monitor_turn(page,'main',1,10,'saved-user')
    assert result['response']==PROSE['text']+'\n\n'+CARD['text']
    assert page.clock==1.5 and page.reads==4


def test_working_and_text_changes_restart_idle_window(monkeypatch):
    page=Page([state(USER,PROSE),state(USER,PROSE,working=True),state(USER,dict(PROSE,text='Full prose'),CARD)])
    clock(monkeypatch,page)
    result=MuseChatClient._monitor_turn(page,'main',1,10,'saved-user')
    assert result['response']=='Full prose\n\n'+CARD['text']
    assert page.clock==2.


def test_timeout_keeps_all_components_without_claiming_completion(monkeypatch):
    page=Page([state(USER,PROSE,CARD,working=True)])
    clock(monkeypatch,page)
    result=MuseChatClient._monitor_turn(page,'main',1,.5,'saved-user')
    assert result['status']=='timeout' and result['response']==PROSE['text']+'\n\n'+CARD['text']
    assert page.clock==.5


def test_identical_text_from_distinct_ids_is_not_dropped(monkeypatch):
    page=Page([state(USER,PROSE,dict(CARD,text=PROSE['text']))])
    clock(monkeypatch,page)
    result=MuseChatClient._monitor_turn(page,'main',1,10,'saved-user')
    assert result['response']==PROSE['text']+'\n\n'+PROSE['text']


def test_repeated_snapshot_does_not_duplicate_components(monkeypatch):
    page=Page([state(USER,PROSE,CARD)])
    clock(monkeypatch,page)
    result=MuseChatClient._monitor_turn(page,'main',1,10,'saved-user')
    assert result['response'].count(PROSE['text'])==1 and result['response'].count(CARD['text'])==1


def test_draft_id_gap_reanchors_only_unique_exact_saved_user(monkeypatch):
    page=Page([state(),state(USER,PROSE,CARD)])
    clock(monkeypatch,page)
    result=MuseChatClient._monitor_turn(page,'main',1,10,'draft-user',new_side_message=USER['text'])
    assert result['turn_message_id']=='saved-user' and page.clock==1.25


def test_idle_get_waits_for_both_hydrated_blocks(monkeypatch):
    page=Page([state(USER,PROSE),state(USER,PROSE,CARD)])
    clock(monkeypatch,page)
    client=MuseChatClient.__new__(MuseChatClient)
    client._open_chat=lambda _:page
    result=client.get_chat('main')
    assert [r['text'] for r in result['messages']]==[USER['text'],PROSE['text'],CARD['text']]
    assert page.clock==1.25


def test_empty_save_gap_resets_pre_save_stability(monkeypatch):
    draft=dict(USER,message_id='draft-user')
    page=Page([state(draft,PROSE),state(),state(USER,PROSE)])
    clock(monkeypatch,page)
    result=MuseChatClient._monitor_turn(page,'main',1,10,'draft-user',new_side_message=USER['text'])
    assert result['turn_message_id']=='saved-user' and page.clock==1.75


def test_settling_cannot_complete_after_total_deadline(monkeypatch):
    page=Page([state(USER,PROSE)])
    clock(monkeypatch,page)
    page.wait_for_timeout=lambda ms:setattr(page,'clock',page.clock+2.)
    result=MuseChatClient._monitor_turn(page,'main',1,1,'saved-user')
    assert result['status']=='timeout'
