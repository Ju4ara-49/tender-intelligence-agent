from bs4 import BeautifulSoup
from src.collectors.fabrikant import FabrikantCollector
from src.collectors.rosatom import RosatomCollector

HTML='''<html><body>
<a href="/files/spec.pdf">ТЗ</a>
<a href="/download/contract.docx">Договор</a>
<a href="#section">section</a>
</body></html>'''

def test_fabrikant_detail_document_contract():
    docs=FabrikantCollector._extract_documents(BeautifulSoup(HTML,"lxml"),"https://fabrikant.ru/procedure/1")
    assert len(docs)==2
    assert docs[0]["url"]=="https://fabrikant.ru/files/spec.pdf"

def test_rosatom_detail_document_contract():
    docs=RosatomCollector._extract_documents(BeautifulSoup(HTML,"lxml"),"https://zakupki.rosatom.ru/proc/1")
    assert len(docs)==2
    assert docs[1]["filename"]=="contract.docx"
