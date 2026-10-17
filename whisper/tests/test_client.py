"""Preserve native segments, word boundaries, timestamps, and spacing."""
import json
from pathlib import Path

import pytest

from whisper_cli.client import WhisperClient
from whisper_cli.parsers import parse_whisper_cpp_words


def token(text,start,end):
    return {'text':text,'offsets':{'from':start,'to':end}}


def data():
    return {'transcription':[{'text':" I'm Casita.",'offsets':{'from':0,'to':500},
        'tokens':[token('[_BEG_]',0,0),token(' I',0,100),token("'m",100,200),
                  token(' Cas',200,300),token('ita',300,450),token('.',450,500),token('[_TT_25]',500,500)]}]}


def test_full_word_mode_preserves_segments_and_original_text(tmp_path):
    source=tmp_path/'source.wav';source.write_bytes(b'audio')
    client=WhisperClient.__new__(WhisperClient)
    client.config=type('Config',(),{'get_cli_executable':lambda self:'whisper-cli'})()
    client._resolve_model=lambda model:'model.bin'
    client._normalize_audio=lambda *args,**kwargs:None
    commands=[]
    def run(command,**kwargs):
        commands.append(command)
        output=Path(command[command.index('-of')+1]+'.json')
        output.write_text(json.dumps(data()))
    client._run=run
    result=client.transcribe(str(source),word_timestamps=True)
    assert '-ojf' in commands[0] and '-ml' not in commands[0]
    assert result['text']=="I'm Casita."
    assert result['segments']==[{'start':0.0,'end':0.5,'text':"I'm Casita."}]
    assert result['words']==[{'start':0.0,'end':0.2,'text':"I'm"},{'start':0.2,'end':0.5,'text':'Casita.'}]


@pytest.mark.parametrize('mutation',[
    lambda d:d['transcription'][0].pop('tokens'),
    lambda d:d['transcription'][0]['tokens'].append(token(' extra',500,600)),
    lambda d:d['transcription'][0]['tokens'][1].pop('offsets'),
    lambda d:d['transcription'][0]['tokens'][1].update(offsets={'from':True,'to':100}),
    lambda d:d['transcription'][0]['tokens'][1].update(offsets={'from':100,'to':0}),
])
def test_missing_or_mismatched_native_word_data_fails_explicitly(mutation):
    value=data();mutation(value)
    with pytest.raises(ValueError):parse_whisper_cpp_words(value)


def test_word_continues_across_native_segment_boundary_without_added_space():
    value={'transcription':[
        {'text':' Cas','tokens':[token(' Cas',10,20)]},
        {'text':'ita. Next','tokens':[token('ita.',20,30),token(' Next',30,30)]}]}
    assert parse_whisper_cpp_words(value)==[{'text':'Casita.','start':0.01,'end':0.03},{'text':'Next','start':0.03,'end':0.03}]
