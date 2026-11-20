import os, json, time, hashlib, unicodedata
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

LIMITE = 800
MODELO = '1000056977'
LOJAS = {'amazon.com.br':'Amazon', 'kabum.com.br':'KaBuM', 'magazineluiza.com.br':'Magalu', 'mercadolivre.com.br':'Mercado Livre', 'fastshop.com.br':'Fast Shop', 'casasbahia.com.br':'Casas Bahia', 'pontofrio.com.br':'Ponto Frio', 'carrefour.com.br':'Carrefour', 'sony.com.br':'Sony', 'playstation.com':'PlayStation'}
ARQUIVO = Path('historico.json')
LINKS_FIXOS = {
    'https://www.kabum.com.br/produto/1071923/controle-sem-fio-sony-dualsense-ps5-edicao-limitada-grand-theft-auto-vi-preto-1000056977',
    'https://www.amazon.com.br/dp/B0HHNVBHQ5',
}

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s).lower()) if not unicodedata.combining(c))

def loja(url):
    p = urlparse(url)
    h = p.hostname or ''
    if p.scheme != 'https': return None
    return next((v for k,v in LOJAS.items() if h == k or h.endswith('.'+k)), None)

def telegram(msg):
    try:
        r = requests.post('https://api.telegram.org/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/sendMessage', json={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':msg}, timeout=20)
        return r.ok and r.json().get('ok', False)
    except (requests.RequestException, ValueError):
        print('Falha de comunicacao com Telegram')
        return False

def percorrer(x):
    if isinstance(x, dict):
        yield x
        for v in x.values(): yield from percorrer(v)
    elif isinstance(x, list):
        for v in x: yield from percorrer(v)

def verificar(url):
    try:
        r = requests.get(url, timeout=15, headers={'User-Agent':'MonitorDePrecos/1.0','Accept-Language':'pt-BR'})
        r.raise_for_status()
        nome_loja = loja(r.url)
        if not nome_loja: return
    except requests.RequestException as e:
        print('Pagina indisponivel:', url, 'HTTP:', e.response.status_code if e.response is not None else 'sem resposta')
        return
    soup = BeautifulSoup(r.text, 'html.parser')
    scripts = soup.find_all('script', type='application/ld+json')
    print('HTTP:', r.status_code, '| URL final:', r.url, '| bytes:', len(r.content), flush=True)
    print('Titulo:', soup.title.get_text(strip=True)[:180] if soup.title else '(sem titulo)', '| JSON-LD:', len(scripts), flush=True)
    print('Metadados de preco:', [(m.get('property') or m.get('itemprop'), m.get('content')) for m in soup.find_all('meta') if 'price' in str(m.get('property') or m.get('itemprop') or '').lower()][:8], flush=True)
    for script in scripts:
        try: dados = json.loads(script.get_text())
        except (ValueError, TypeError): continue
        for p in percorrer(dados):
            tipos = p.get('@type', [])
            if isinstance(tipos,str): tipos = [tipos]
            if not isinstance(tipos,list) or 'Product' not in tipos: continue
            nome = str(p.get('name',''))
            print('Product encontrado:', nome[:180], '| SKU:', p.get('sku'), '| MPN:', p.get('mpn'), flush=True)
            texto = norm(nome)
            codigo = MODELO in ' '.join(str(p.get(k,'')) for k in ('name','sku','mpn','model','gtin'))
            if '1000056978' in str(p) or 'branco' in texto or 'white' in texto: continue
            if not (codigo or ('dualsense' in texto and any(t in texto for t in ('gta vi','gta 6','grand theft auto vi')) and any(t in texto for t in ('preto','black')))): continue
            if any(t in texto for t in ('adesivo','capa','skin','case','replica','usado','personalizado','customizado','carcaca','shell','seminovo')): continue
            ofertas = p.get('offers', [])
            if isinstance(ofertas,dict): ofertas = [ofertas]
            if not isinstance(ofertas,list): continue
            for o in ofertas:
                if not isinstance(o,dict): continue
                print('Dados da oferta:', {k: o.get(k) for k in ('@type','price','priceCurrency','availability','itemCondition')}, flush=True)
                if str(o.get('priceCurrency','')).upper() != 'BRL': continue
                estoque = str(o.get('availability','')).rstrip('/').split('/')[-1]
                if estoque not in ('InStock','OutOfStock','PreOrder','BackOrder','SoldOut','Discontinued','LimitedAvailability'): continue
                if any(t in str(o.get('itemCondition','')) for t in ('UsedCondition','RefurbishedCondition','DamagedCondition')): continue
                try: preco = float(o['price'])
                except (KeyError, ValueError, TypeError): continue
                if not 0 < preco < float('inf'): continue
                vendedor = o.get('seller',{})
                if isinstance(vendedor,dict): vendedor = vendedor.get('name','')
                yield nome, preco, nome_loja, vendedor or 'Nao informado', r.url, codigo, estoque

def main():
    print('Monitor v2.4 - alertas de estoque', flush=True)
    if os.getenv('TESTE_TELEGRAM','').lower() == 'true':
        if not telegram(f'✅ Monitor GTA VI conectado! Limite: até R$ {LIMITE}. Busca a cada hora.'): raise SystemExit('Falha no teste do Telegram. Confira os Secrets.')
    historico = json.loads(ARQUIVO.read_text(encoding='utf-8')) if ARQUIVO.exists() else {}
    links = set(LINKS_FIXOS)
    consultas = ['"DualSense" "GTA VI" controle Brasil', '"1000056977" controle Brasil', '"DualSense" "Grand Theft Auto VI" edição limitada Brasil']
    sucesso = 0
    for q in consultas:
        try:
            for item in DDGS(timeout=15).text(q, region='br-pt', max_results=25):
