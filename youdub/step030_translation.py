# -*- coding: utf-8 -*-
import json
import os
import re
import openai
from dotenv import load_dotenv
import time
from loguru import logger

load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')
openai.api_base = os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
model_name = os.getenv('MODEL_NAME', 'gpt-3.5-turbo')

def get_necessary_info(info: dict):
    return {
        'title': info['title'],
        'uploader': info['uploader'],
        'description': info['description'],
        'upload_date': info['upload_date'],
        'categories': info['categories'],
        'tags': info['tags'],
    }


def summarize(info, transcript, target_language='简体中文'):
    transcript = ' '.join(line['text'] for line in transcript)
    info_message = f'This is a video called "{info["title"]}" by {info["uploader"]}. ' \
        + f'It was uploaded on {info["upload_date"]}. ' \
    
    full_description = f'The following is the full content of the video:\n{transcript}\n{info_message}\nIn Json format:\n```json\n{{"title": "the title of the video", "summary", "the summary of the video"}}\n```\nSummarize the video in JSON format: '
    
    messages = [
        {'role': 'system', 'content': f'You are a expert in the field of this video. Please summarize the video in JSON format.'},
        {'role': 'user', 'content': full_description},
    ]
    retry = 0
    while retry < 10 and retry != -1:
        try:
            response = openai.ChatCompletion.create(
                model=model_name,
                messages=messages,
                timeout=240
            )
            summary = response.choices[0].message.content.replace('\n', '')
            logger.info(summary)
            summary = re.findall(r'\{.*?\}', summary)[0]
            summary = json.loads(summary)
            messages = [
                {'role': 'system', 'content': f'You are a native speaker of {target_language}. Please translate the title and summary into {target_language} in JSON format.'},
                {'role': 'user',
                    'content': f'The title of the video is "{summary["title"]}". The summary of the video is "{summary["summary"]}". Please translate the title and summary into {target_language} in JSON format. ```json\n{{"title": "the {target_language} title of the video", "summary", "the {target_language} summary of the video"}}\n```. Remember to tranlate both the title and the summary into {target_language} in JSON.'},
            ]
            response = openai.ChatCompletion.create(
                model=model_name,
                messages=messages,
                timeout=240
            )
            summary = response.choices[0].message.content.replace('\n', '')
            logger.info(summary)
            summary = re.findall(r'\{.*?\}', summary)[0]
            summary = json.loads(summary)
            result = {
                'title': summary['title'],
                'author': info['uploader'],
                'summary': summary['summary'],
                'language': target_language,
            }
            return result
        except Exception as e:
            retry += 1
            logger.warning('总结失败')
            time.sleep(1)


def translation_postprocess(result):
    result = re.sub(r'\（[^)]*\）', '', result)
    result = result.replace('...', '，')
    result = re.sub(r'(?<=\d),(?=\d)', '', result)
    result = result.replace('²', '的平方').replace(
        '————', '：').replace('——', '：').replace('°', '度')
    result = result.replace("AI", '人工智能')
    result = result.replace('变压器', "Transformer")
    return result

def valid_translation(text, translation):
    forbidden = ['翻译', '这句', '\n']
    for word in forbidden:
        if word in translation:
            return False, f"Don't include {word} in the translation. Only translate the following sentence and give me the result."
    if (translation.startswith('“') and translation.endswith('”')) or (translation.startswith('"') and translation.endswith('"')):
        translation = translation[1:-1]
        
    if len(text) <= 10 and len(translation) > 10:
        if len(translation) > 20:
            return False, f'Only translate the following sentence and give me the result.'
    elif len(translation) > len(text)*0.75:
        return False, f'The translation is too long. Only translate the following sentence and give me the result.'
    
    return True, translation_postprocess(translation)
    
def _translate(summary, transcript, target_language='简体中文'):
    info = f'This is a video called "{summary["title"]}". {summary["summary"]}.'
    full_translation = []
    fixed_message = [
        {'role': 'system', 'content': f'You are a expert in the field of this video.\n{info}\nPlease translate the sentence into {target_language}.'},
        {'role': 'user', 'content': 'What language do you need to translate the title into?'},
        {'role': 'assistant', 'content': target_language}]
    
    for line in transcript:
        text = line['text']
        history = ''.join(full_translation[:-30])
        
        retry_message = 'Only translate the following sentence and give me the final translation.'
        retry = 0
        while retry < 30 and retry != -1:
            messages = fixed_message + \
                [{'role': 'user', 'content': '\n'.join(
                    [history, retry_message, f'Please translate the single following sentence into {target_language}: "{text}"'])}]
            try:
                response = openai.ChatCompletion.create(
                    model=model_name,
                    messages=messages,
                    timeout=240
                )
                translation = response.choices[0].message.content.replace('\n', '')
                logger.info(f'原文：{text}')
                logger.info(f'译文：{translation}')
                success, translation = valid_translation(text, translation)
                if not success:
                    retry_message += 'Only translate the following sentence and give me the final translation.'
                    raise Exception('Invalid translation')
                full_translation.append(translation)
                retry = -1
            except Exception as e:
                retry += 1
                logger.warning('翻译失败')
                time.sleep(1)
    return full_translation

def translate(folder, target_language='简体中文'):
    if os.path.exists(os.path.join(folder, 'translation.json')):
        logger.info(f'Translation already exists in {folder}')
        return True
    
    info_path = os.path.join(folder, 'download.info.json')
    if not os.path.exists(info_path):
        return False
    # info_path = r'videos\Lex Clips\20231222 Jeff Bezos on fear of death ｜ Lex Fridman Podcast Clips\download.info.json'
    with open(info_path, 'r', encoding='utf-8') as f:
        info = json.load(f)
    info = get_necessary_info(info)
    
    transcript_path = os.path.join(folder, 'transcript.json')
    with open(transcript_path, 'r', encoding='utf-8') as f:
        transcript = json.load(f)
    
    summary_path = os.path.join(folder, 'summary.json')
    summary = summarize(info, transcript, target_language)
    if summary is None:
        logger.error(f'Failed to summarize {folder}')
        return False
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    translation_path = os.path.join(folder, 'translation.json')
    translation = _translate(summary, transcript, target_language)
    for i, line in enumerate(transcript):
        line['translation'] = translation[i]
    with open(translation_path, 'w', encoding='utf-8') as f:
        json.dump(transcript, f, indent=2, ensure_ascii=False)
    return True

def translate_all_transcript_under_folder(folder, target_language):
    for root, dirs, files in os.walk(folder):
        if 'transcript.json' in files and 'translation.json' not in files:
            translate(root, target_language)
    return f'Translated all videos under {folder}'

if __name__ == '__main__':
    translate_all_transcript_under_folder('videos', '简体中文')
    