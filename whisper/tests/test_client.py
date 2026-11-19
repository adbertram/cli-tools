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
    lambda d:d['transcription'][0]['tokens'][1].update(offsets={'from':-1,'to':100}),
    lambda d:d['transcription'][0]['tokens'][1].update(offsets={'from':0,'to':-1}),
])
def test_missing_or_mismatched_native_word_data_fails_explicitly(mutation):
    value=data();mutation(value)
    with pytest.raises(ValueError):parse_whisper_cpp_words(value)


def test_word_continues_across_native_segment_boundary_without_added_space():
    value={'transcription':[
        {'text':' Cas','tokens':[token(' Cas',10,20)]},
        {'text':'ita. Next','tokens':[token('ita.',20,30),token(' Next',30,30)]}]}
    assert parse_whisper_cpp_words(value)==[{'text':'Casita.','start':0.01,'end':0.03},{'text':'Next','start':0.03,'end':0.03}]


def test_reversed_token_run_after_prior_segment_starts_at_previous_token_end():
    value={'transcription':[
        {'text':' Done.','tokens':[token('[_BEG_]',0,0),token(' Done',6000,6770),token('.',6770,7000),token('[_TT_350]',7000,7000)]},
        {'text':' And both const edits','tokens':[token('[_BEG_]',10000,10000),token(' And',10000,7560),token(' both',10000,8310),
                                                 token(' const',10000,9240),token(' edits',10000,10160)]}]}
    assert parse_whisper_cpp_words(value)==[
        {'text':'Done.','start':6.0,'end':7.0},{'text':'And','start':7.0,'end':7.56},{'text':'both','start':7.56,'end':8.31},
        {'text':'const','start':8.31,'end':9.24},{'text':'edits','start':10.0,'end':10.16}]


def test_reversed_continuation_token_joins_word():
    value={'transcription':[
        {'text':'. That',"tokens":[token('.',16000,16000),token(' That',17000,16360)]},
        {'text':"'s a",'tokens':[token("'s",17000,16540),token(' a',17000,16630)]}]}
    assert parse_whisper_cpp_words(value)==[
        {'text':'.','start':16.0,'end':16.0},{'text':"That's",'start':16.0,'end':16.54},{'text':'a','start':16.54,'end':16.63}]


def test_reversed_first_token_starts_at_its_own_end():
    value={'transcription':[{'text':' And both','tokens':[token(' And',10000,7560),token(' both',10000,8310)]}]}
    assert parse_whisper_cpp_words(value)==[{'text':'And','start':7.56,'end':7.56},{'text':'both','start':7.56,'end':8.31}]
