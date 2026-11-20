import os, json, time, hashlib, unicodedata
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

LIMITE = 600
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
            codigo = MODELO in ' '.join(str(p.get(k,'')) for k in ('sku','mpn','model','gtin'))
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
                if str(o.get('availability','')).rstrip('/').split('/')[-1] != 'InStock': continue
                if any(t in str(o.get('itemCondition','')) for t in ('UsedCondition','RefurbishedCondition','DamagedCondition')): continue
                try: preco = float(o['price'])
                except (KeyError, ValueError, TypeError): continue
                if not 0 < preco < float('inf'): continue
                vendedor = o.get('seller',{})
                if isinstance(vendedor,dict): vendedor = vendedor.get('name','')
                yield nome, preco, nome_loja, vendedor or 'Nao informado', r.url, codigo

def main():
    print('Monitor v2.1 - diagnostico de paginas', flush=True)
    if os.getenv('TESTE_TELEGRAM','').lower() == 'true':
        if not telegram('✅ Monitor GTA VI conectado! Limite: abaixo de R$ 600. Busca a cada hora.'): raise SystemExit('Falha no teste do Telegram. Confira os Secrets.')
    historico = json.loads(ARQUIVO.read_text(encoding='utf-8')) if ARQUIVO.exists() else {}
    links = set(LINKS_FIXOS)
    consultas = ['"DualSense" "GTA VI" controle Brasil', '"1000056977" controle Brasil', '"DualSense" "Grand Theft Auto VI" edição limitada Brasil']
    sucesso = 0
    for q in consultas:
        try:
            for item in DDGS(timeout=15).text(q, region='br-pt', max_results=25):
                u = item.get('href','')
                if loja(u): links.add(u)
            sucesso += 1
        except Exception as e: print('Falha de busca:', type(e).__name__, str(e)[:350], flush=True)
        time.sleep(2)
    if not sucesso: print('Todas as buscas falharam; continuando com os links fixos.')
    print('Links encontrados:',len(links))
    verificadas = 0
    falhas = 0
    for url in sorted(links, key=lambda u: (u not in LINKS_FIXOS, u)):
        print('Consultando:', url)
        for nome, preco, origem, vendedor, link, codigo in verificar(url):
            verificadas += 1
            print(origem, nome, preco)
            if preco >= LIMITE: continue
            chave = hashlib.sha256((link+'|'+str(vendedor)).encode()).hexdigest()
            if chave in historico and preco >= historico[chave]: continue
            valor = f'{preco:.2f}'.replace('.',',')
            modelo = 'Codigo identificado' if codigo else 'Nome compativel; confira o codigo'
            msg = f'🚨 POSSÍVEL OFERTA GTA VI\n\n🎮 {nome}\n💰 R$ {valor}\n🏪 {origem}\n👤 Vendedor: {vendedor}\n📦 Estoque declarado na pagina\n🔎 {modelo}\n\nConfira vendedor, originalidade, frete, impostos e preco final.\n🔗 {link}'
            if telegram(msg):
                historico[chave] = preco
                ARQUIVO.write_text(json.dumps(historico,indent=2)+'\n',encoding='utf-8')
            else: falhas += 1
        time.sleep(1)
    print('Ofertas verificadas:',verificadas)
    if not verificadas: raise SystemExit('Nenhuma oferta validada; confira os logs. Isso nao comprova ausencia de estoque.')
    if falhas: raise SystemExit('Falha ao enviar uma ou mais notificacoes.')

if __name__ == '__main__': main()
