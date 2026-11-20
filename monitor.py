"""Monitor DualSense GTA VI preto. Sem APIs pagas."""
import os, json, re, time, unicodedata
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

LIMITE = 800
MODELO = '1000056977'
ARQUIVO = Path('historico.json')
LOJAS = {'amazon.com.br':'Amazon', 'kabum.com.br':'KaBuM', 'magazineluiza.com.br':'Magalu', 'mercadolivre.com.br':'Mercado Livre', 'fastshop.com.br':'Fast Shop', 'casasbahia.com.br':'Casas Bahia', 'pontofrio.com.br':'Ponto Frio', 'carrefour.com.br':'Carrefour', 'sony.com.br':'Sony', 'playstation.com':'PlayStation', 'americanas.com.br':'Americanas'}
FIXOS = ['https://www.kabum.com.br/produto/1071923/controle-sem-fio-sony-dualsense-ps5-edicao-limitada-grand-theft-auto-vi-preto-1000056977', 'https://www.amazon.com.br/dp/B0HHNVBHQ5']
STATUS = {'InStock':'Em estoque', 'OutOfStock':'Sem estoque', 'SoldOut':'Sem estoque', 'PreOrder':'Pré-venda', 'BackOrder':'Sob encomenda', 'LimitedAvailability':'Disponibilidade limitada', 'Discontinued':'Descontinuado'}

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s).lower()) if not unicodedata.combining(c))

def loja(url):
    p = urlparse(url)
    h = p.hostname or ''
    return next((v for k,v in LOJAS.items() if p.scheme == 'https' and (h == k or h.endswith('.'+k))), None)

def canon(url):
    p = urlparse(url)
    m = re.search(r'/dp/([A-Z0-9]{10})', p.path, re.I)
    if loja(url) == 'Amazon' and m: return 'https://www.amazon.com.br/dp/'+m.group(1).upper()
    m = re.search(r'/produto/(\d+)', p.path)
    if loja(url) == 'KaBuM' and m and m.group(1)=='1071923': return FIXOS[0]
    return urlunparse((p.scheme,p.netloc,p.path,'','',''))

def telegram(msg):
    try:
        r = requests.post('https://api.telegram.org/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/sendMessage', json={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':msg,'disable_web_page_preview':True}, timeout=20)
        ok = r.ok and r.json().get('ok',False)
        print('Telegram:', 'enviado' if ok else f'falha HTTP {r.status_code}', flush=True)
        return ok
    except (requests.RequestException, ValueError, KeyError):
        print('Telegram: falha de comunicação ou configuração', flush=True)
        return False

def salvar(h):
    tmp=ARQUIVO.with_suffix('.tmp'); tmp.write_text(json.dumps(h,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); tmp.replace(ARQUIVO)

def percorrer(x):
    if isinstance(x,dict):
        yield x
        for v in x.values(): yield from percorrer(v)
    elif isinstance(x,list):
        for v in x: yield from percorrer(v)

def corresponde(nome, identificadores=''):
    t=norm(nome)
    if any(x in t for x in ('branco','white','adesivo','capa','skin','case','replica','usado','personalizado','customizado','carcaca','shell','seminovo')) or '1000056978' in str(identificadores): return False
    return MODELO in str(nome)+' '+str(identificadores) or ('dualsense' in t and any(x in t for x in ('gta vi','gta 6','grand theft auto vi')) and any(x in t for x in ('preto','black')))

def preco_num(x):
    try:
        s=str(x).strip().replace('R$','').strip()
        if ',' in s: s=s.replace('.','').replace(',','.')
        v=float(s)
        return v if 0<v<float('inf') else None
    except (ValueError,TypeError): return None

def extrair(soup, url):
    origem=loja(url)
    for script in soup.find_all('script',type='application/ld+json'):
        try: dados=json.loads(script.get_text())
        except (ValueError,TypeError): continue
        for p in percorrer(dados):
            tipos=p.get('@type',[])
            if isinstance(tipos,str): tipos=[tipos]
            if not isinstance(tipos,list) or 'Product' not in tipos: continue
            nome=str(p.get('name',''))
            ids=' '.join(str(p.get(k,'')) for k in ('sku','mpn','model','gtin'))
            if not corresponde(nome,ids): continue
            ofertas=p.get('offers',[])
            if isinstance(ofertas,dict): ofertas=[ofertas]
            if not isinstance(ofertas,list): continue
            for o in ofertas:
                if not isinstance(o,dict) or str(o.get('@type',''))=='AggregateOffer': continue
                if str(o.get('priceCurrency','')).upper()!='BRL': continue
                if any(x in str(o.get('itemCondition','')) for x in ('UsedCondition','RefurbishedCondition','DamagedCondition')): continue
                st=str(o.get('availability','')).rstrip('/').split('/')[-1]
                v=preco_num(o.get('price'))
                if st not in STATUS: continue
                seller=o.get('seller',{})
                if isinstance(seller,dict): seller=seller.get('name','')
                yield dict(nome=nome,loja=origem,vendedor=str(seller or 'Não informado'),preco=v,status=STATUS[st],url=canon(url))
    # Amazon: fallback apenas com título e disponibilidade explícitos na página.
    if origem=='Amazon':
        title=soup.select_one('#productTitle'); av=soup.select_one('#availability')
        if title and av and corresponde(title.get_text(' ',strip=True)):
            t=norm(av.get_text(' ',strip=True))
            st=next((s for termos,s in [(('nao disponivel','indisponivel','sem estoque'),'Sem estoque'),(('pre-venda',),'Pré-venda'),(('em estoque',),'Em estoque')] if any(x in t for x in termos)),None)
            if st:
                pr=soup.select_one('#corePrice_feature_div .a-offscreen, #corePriceDisplay_desktop_feature_div .a-offscreen')
                seller=soup.select_one('#sellerProfileTrigger')
                yield dict(nome=title.get_text(' ',strip=True),loja=origem,vendedor=seller.get_text(' ',strip=True) if seller else 'Não informado',preco=preco_num(pr.get_text(strip=True)) if pr else None,status=st,url=canon(url))

def verificar(url):
    try:
        r=requests.get(url,timeout=15,headers={'User-Agent':'MonitorDePrecos/3.0','Accept-Language':'pt-BR,pt;q=0.9'})
        r.raise_for_status()
        if not loja(r.url): return [],'redirecionamento fora das lojas permitidas'
        soup=BeautifulSoup(r.text,'html.parser')
        ofertas=list(extrair(soup,r.url))
        if not ofertas: return [],f'HTTP {r.status_code}; sem dados válidos ({len(r.content)} bytes)'
        return ofertas,'OK'
    except requests.RequestException as e:
        return [],f'HTTP {e.response.status_code}' if e.response is not None else type(e).__name__

def descobrir():
    from ddgs import DDGS
    links=set(); ok=0
    for backend in ('duckduckgo','bing','brave'):
        try:
            itens=DDGS(timeout=12).text(f'"{MODELO}" DualSense GTA VI Brasil',region='br-pt',max_results=15,backend=backend)
            ok+=1
            for item in itens:
                u=item.get('href','')
                if loja(u): links.add(canon(u))
            print('Busca',backend,':',len(itens),'resultados',flush=True)
        except Exception as e: print('Busca',backend,':',type(e).__name__,str(e)[:120],flush=True)
    return links,ok

def chave(o):
    return '|'.join((MODELO,o['loja'],norm(o['vendedor'])))

def registrar(o,h,forcar=False):
    k=chave(o); anterior=h.get(k); estado={'preco':o['preco'],'status':o['status']}
    v=o['preco']; elegivel=v is not None and v<=LIMITE
    if not elegivel:
        # Preserva a mudança para notificar quando retornar ao orçamento.
        h[k]=estado; return 'fora do limite ou sem preço'
    if not forcar and anterior==estado: return 'duplicado ignorado'
    titulo='🚨 POSSÍVEL OFERTA' if o['status']=='Em estoque' else '⚠️ '+o['status'].upper()
    valor=f"R$ {v:.2f}".replace('.',',')
    msg=f"{titulo} — DualSense GTA VI preto\n💰 {valor}\n🏪 {o['loja']}\n👤 Vendedor: {o['vendedor']}\n📦 {o['status']} segundo a página\n🔗 {o['url']}\nConfira vendedor, frete, impostos e preço final."
    if not telegram(msg): return 'falha Telegram'
    h[k]=estado; salvar(h); return 'notificado'

def main():
    print('Monitor v3.0 — múltiplas buscas e relatório',flush=True)
    h=json.loads(ARQUIVO.read_text(encoding='utf-8')) if ARQUIVO.exists() else {}
    teste=os.getenv('TESTE_TELEGRAM','').lower()=='true'
    if teste and not telegram('✅ Monitor v3.0 conectado. Limite R$ 800. Teste manual com relatório.'): raise SystemExit(1)
    novos,ok=descobrir(); links=list(dict.fromkeys(FIXOS+list(h.get('_links',[]))+sorted(novos)))[:25]
    resultados={}; erros=[]; validados=set()
    for u in links:
        if not loja(u): continue
        print('Consultando:',u,flush=True)
        ofertas,diag=verificar(u)
        if not ofertas: erros.append(f'{loja(u)}: {diag}'); print(diag,flush=True)
        else: validados.add(u)
        for o in ofertas:
            k=chave(o)
            # Prefere oferta com preço informado, depois disponibilidade e menor preço.
            rank=lambda x:(x['preco'] is None,x['status']!='Em estoque',x['preco'] or float('inf'))
            if k not in resultados or rank(o)<rank(resultados[k]): resultados[k]=o
        time.sleep(1)
    h['_links']=sorted(validados-set(FIXOS))[:20]
    falhas=0; linhas=[]
    for o in resultados.values():
        acao=registrar(o,h); falhas+=acao=='falha Telegram'
        linha=f"{o['loja']}: {o['status']} | "+(f"R$ {o['preco']:.2f}" if o['preco'] is not None else 'preço não confirmado')+f" | {acao}"
        print(linha,flush=True); linhas.append(linha)
    agora=datetime.now(ZoneInfo('America/Sao_Paulo')); dia=agora.date().isoformat()
    if teste or (agora.hour>=8 and h.get('_resumo')!=dia):
        msg='📋 Relatório monitor GTA VI\n'+ '\n'.join(linhas+erros)[:3000]+f'\nBuscadores com resposta: {ok}/3\nLojas não verificadas não significam falta de estoque.'
        if telegram(msg):
            if not teste: h['_resumo']=dia
        else: falhas+=1
    salvar(h)
    print('Ofertas verificadas:',len(resultados),'| Consultas sem validação:',len(erros),flush=True)
    if not resultados or falhas: raise SystemExit(1)

if __name__=='__main__': main()
