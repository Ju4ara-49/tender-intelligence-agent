from bs4 import BeautifulSoup
from src.collectors.eis_zakupki import EisZakupkiCollector
from src.collectors.b2b_center import B2BCenterCollector

HTML='''<html><body>
<a href="/docs/spec.pdf">Техническое задание</a>
<a href="/download?id=2">Скачать документ</a>
<a href="javascript:void(0)">bad</a>
</body></html>'''

def test_eis_extracts_attachments():
    docs=EisZakupkiCollector._extract_documents(BeautifulSoup(HTML,"lxml"),"https://zakupki.gov.ru/item")
    assert [d["url"] for d in docs]==["https://zakupki.gov.ru/docs/spec.pdf","https://zakupki.gov.ru/download?id=2"]

def test_b2b_extracts_attachments():
    docs=B2BCenterCollector._extract_documents(BeautifulSoup(HTML,"lxml"),"https://www.b2b-center.ru/trade")
    assert len(docs)==2
    assert docs[0]["filename"]=="Техническое задание"
