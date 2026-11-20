"""Monitor universal de produtos. Sem APIs pagas."""
import os, json, re, time, unicodedata
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

ARQUIVO = Path('historico.json')
LOJAS = {'amazon.com.br':'Amazon', 'kabum.com.br':'KaBuM', 'magazineluiza.com.br':'Magalu', 'mercadolivre.com.br':'Mercado Livre', 'fastshop.com.br':'Fast Shop', 'casasbahia.com.br':'Casas Bahia', 'pontofrio.com.br':'Ponto Frio', 'carrefour.com.br':'Carrefour', 'sony.com.br':'Sony', 'playstation.com':'PlayStation', 'americanas.com.br':'Americanas', 'wafuu.com':'WAFUU', 'bestbuy.com':'Best Buy', 'amazon.com':'Amazon EUA'}
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
    # Preserve full KaBuM product slug.
    return urlunparse((p.scheme,p.netloc,p.path,'','',''))

def telegram(msg, teclado=None):
    try:
        r = requests.post('https://api.telegram.org/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/sendMessage', json={'chat_id':os.environ['TELEGRAM_CHAT_ID'],'text':msg,'disable_web_page_preview':True, **({'reply_markup':teclado} if teclado else {})}, timeout=20)
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

def corresponde(nome, identificadores, cfg):
    t=norm(nome+' '+str(identificadores))
    excluidos=['adesivo','capa para','skin','case para','replica','usado','carcaca','shell','seminovo','recondicionado']+cfg.get('termos_excluidos',[])
    if any(norm(x) in t for x in excluidos): return False
    modelo=norm(cfg.get('modelo',''))
    grupos=cfg.get('termos_obrigatorios',[])
    return bool((modelo and re.search(r'(?<![a-z0-9])'+re.escape(modelo)+r'(?![a-z0-9])',t)) or (grupos and all(any(norm(x) in t for x in (g if isinstance(g,list) else [g])) for g in grupos)))

def preco_num(x):
    try:
        s=str(x).strip().replace('R$','').strip()
        if ',' in s: s=s.replace('.','').replace(',','.')
        v=float(s)
        return v if 0<v<float('inf') else None
    except (ValueError,TypeError): return None

def custo(o, cfg):
    moeda=str(o.get('priceCurrency','')).upper()
    v=preco_num(o.get('price'))
    if v is None: return None
    if moeda=='BRL' and loja(cfg.get('_url','')) not in ('WAFUU','Best Buy','Amazon EUA'): return v
    # Somente estimativa explicitamente configurada; nunca presume impostos zero.
    c=cfg.get('importacao',{}).get(moeda,{})
    try:
        taxa=float(c['cambio']); frete=float(c['frete_brl']); imposto=float(c['impostos_brl'])
        if not all(0<=x<float('inf') for x in (taxa,frete,imposto)) or taxa<=0: return None
        return round(v*taxa+frete+imposto,2)
    except (KeyError,TypeError,ValueError): return None

def extrair(soup, url, cfg):
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
            if not corresponde(nome,ids,cfg): continue
            ofertas=p.get('offers',[])
            if isinstance(ofertas,dict): ofertas=[ofertas]
            if not isinstance(ofertas,list): continue
            for o in ofertas:
                if not isinstance(o,dict) or str(o.get('@type',''))=='AggregateOffer': continue
                if not o.get('priceCurrency'): continue
                if any(x in str(o.get('itemCondition','')) for x in ('UsedCondition','RefurbishedCondition','DamagedCondition')): continue
                st=str(o.get('availability','')).rstrip('/').split('/')[-1]
                v=custo(o,dict(cfg,_url=url))
                if st not in STATUS: continue
                seller=o.get('seller',{})
                if isinstance(seller,dict): seller=seller.get('name','')
                yield dict(nome=nome,loja=origem,vendedor=str(seller or 'Não informado'),preco=v,status=STATUS[st],url=canon(url),estimativa=(origem in ('WAFUU','Best Buy','Amazon EUA') or str(o.get('priceCurrency','')).upper()!='BRL'))
    # Amazon: fallback apenas com título e disponibilidade explícitos na página.
    if origem=='Amazon':
        title=soup.select_one('#productTitle'); av=soup.select_one('#availability')
        if title and av and corresponde(title.get_text(' ',strip=True),'',cfg):
            t=norm(av.get_text(' ',strip=True))
            st=next((s for termos,s in [(('nao disponivel','indisponivel','sem estoque','nao esta disponivel'),'Sem estoque'),(('pre-venda',),'Pré-venda'),(('em estoque',),'Em estoque')] if any(x in t for x in termos)),None)
            if st:
                pr=soup.select_one('#corePrice_feature_div .a-offscreen, #corePriceDisplay_desktop_feature_div .a-offscreen')
                seller=soup.select_one('#sellerProfileTrigger')
                if not pr or preco_num(pr.get_text(strip=True)) is None: return
                yield dict(nome=title.get_text(' ',strip=True),loja=origem,vendedor=seller.get_text(' ',strip=True) if seller else 'Não informado',preco=preco_num(pr.get_text(strip=True)) if pr else None,status=st,url=canon(url))

    # Microdata: only a Product container with matching name and explicit Offer.
    for node in soup.select('[itemscope][itemtype$="/Product"]'):
        def prop(root, name):
            el=root.select_one('[itemprop="'+name+'"]')
            return (el.get('content') or el.get('href') or el.get_text(' ',strip=True)) if el else ''
        nome=prop(node,'name')
        if not corresponde(nome, ' '.join(prop(node,k) for k in ('sku','mpn','model')),cfg): continue
        for offer in node.select('[itemscope][itemtype$="/Offer"]'):
            st=prop(offer,'availability').rstrip('/').split('/')[-1]
            if st not in STATUS or not prop(offer,'priceCurrency'): continue
            if any(x in prop(offer,'itemCondition') for x in ('UsedCondition','RefurbishedCondition','DamagedCondition')): continue
            v=custo({'price':prop(offer,'price'),'priceCurrency':prop(offer,'priceCurrency')},dict(cfg,_url=url))
            if v is None: continue
            yield dict(nome=nome,loja=origem,vendedor=prop(offer,'seller') or 'Não informado',preco=v,status=STATUS[st],url=canon(url),estimativa=origem in ('WAFUU','Best Buy','Amazon EUA') or prop(offer,'priceCurrency').upper()!='BRL')

def pagina_produto(url):
    p=urlparse(url); path=p.path.lower()
    if loja(url)=='Magalu': return '/p/' in path and '/busca/' not in path
    if loja(url) in ('Amazon','Amazon EUA'): return bool(re.search(r'/dp/[a-z0-9]{10}',path))
    if loja(url)=='PlayStation' and 'store.playstation.com' in p.netloc: return False
    return not any(x in path for x in ('/busca/','/search/'))

def verificar(url,cfg):
    try:
        if not pagina_produto(url): return [],'página de busca ignorada; use link direto'
        r=requests.get(url,timeout=15,headers={'User-Agent':'MonitorDePrecos/6.0','Accept-Language':'pt-BR,pt;q=0.9'})
        r.raise_for_status()
        if not loja(r.url): return [],'redirecionamento fora das lojas permitidas'
        soup=BeautifulSoup(r.text,'html.parser')
        ofertas=list(extrair(soup,r.url,cfg))
        if not ofertas: return [],f'HTTP {r.status_code}; sem dados válidos ({len(r.content)} bytes)'
        return ofertas,'OK'
    except requests.RequestException as e:
        return [],f'HTTP {e.response.status_code}' if e.response is not None else type(e).__name__

def descobrir(cfg):
    from ddgs import DDGS
    links=set(); ok=0
    for backend in ('bing','duckduckgo','brave'):
        try:
            consulta=cfg.get('consulta') or cfg['nome']
            if backend=='brave': consulta=cfg['nome']+' '+cfg.get('modelo','')+' Brasil'
            itens=DDGS(timeout=12).text(consulta,region='br-pt',max_results=15,backend=backend)
            ok+=1
            for item in itens:
                u=item.get('href','')
                if loja(u) and pagina_produto(u): links.add(canon(u))
            print('Busca',backend,':',len(itens),'resultados',flush=True)
        except Exception as e: print('Busca',backend,':',type(e).__name__,str(e)[:120],flush=True)
    return links,ok

def chave(o):
    return '|'.join((o['loja'],norm(o['vendedor'])))


def registrar(o,h,cfg):
    k=chave(o); anterior=h.get(k)
    estado={'preco':o['preco'],'status':o['status']}
    v=o['preco']; status=o['status']
    permitido=(status=='Em estoque' or
               (status=='Sem estoque' and cfg.get('avisar_sem_estoque',False)) or
               (status in ('Pré-venda','Sob encomenda','Disponibilidade limitada') and cfg.get('avisar_pre_venda',False)))
    elegivel=v is not None and v<=cfg['preco_maximo'] and permitido
    estado['elegivel']=elegivel
    if not elegivel:
        h[k]=estado; return 'fora do filtro ou sem preço confirmado'
    if anterior==estado: return 'duplicado ignorado'
    titulo='🚨 POSSÍVEL OFERTA' if status=='Em estoque' else '⚠️ '+status.upper()
    valor=f"R$ {v:.2f}".replace('.',',')
    msg=f"{titulo} — {cfg['nome']}\n💰 {valor}\n🏪 {o['loja']}\n👤 Vendedor: {o['vendedor']}\n📦 {status} segundo a página\n🔗 {o['url']}\nConfira vendedor, produto, frete e preço final."
    if o.get('estimativa'): msg+='\nImportação: estimativa manual, não é preço final confirmado.'
    if not telegram(msg): return 'falha Telegram'
    h[k]=estado; return 'notificado'


def carregar_produtos():
    configs=json.loads(Path('produtos.json').read_text(encoding='utf-8-sig'))
    if not isinstance(configs,list): raise ValueError('produtos.json deve conter uma lista')
    ids=set()
    for c in configs:
        if not isinstance(c,dict): raise ValueError('Cada produto deve ser um objeto')
        if not isinstance(c.get('id'),str) or not c['id'].strip() or c['id'] in ids: raise ValueError('IDs devem ser únicos e não vazios')
        ids.add(c['id'])
        if not isinstance(c.get('nome'),str) or not c['nome'].strip(): raise ValueError('Nome obrigatório')
        if type(c.get('preco_maximo')) not in (int,float) or not 0<c['preco_maximo']<float('inf'): raise ValueError('Preço máximo deve ser positivo')
        if not c.get('modelo') and not c.get('termos_obrigatorios'): raise ValueError('Informe modelo ou termos obrigatórios para '+c['id'])
        for u in c.get('links',[]):
            if not loja(u): raise ValueError('Link fora das lojas permitidas: '+u)
    return configs


BLOQUEADAS_EXECUCAO=set()

def monitorar(cfg,h,cache):
    print('Produto:',cfg['nome'],flush=True)
    novos,ok=descobrir(cfg) if cfg.get("descobrir",True) else (set(),0)
    fixos=cfg.get('links',[])
    links=list(dict.fromkeys(fixos+h.get('links',[])+sorted(novos)))[:15]
    resultados={}; erros=[]; validados=set(); falhas=0; bloqueadas=BLOQUEADAS_EXECUCAO
    for u in links:
        if loja(u) in bloqueadas:
            erros.append(f'{loja(u)}: consulta suspensa nesta execução após bloqueio'); continue
        print('Consultando:',u,flush=True)
        ofertas,diag=verificar(u,cfg)
        if not ofertas:
            erros.append(f'{loja(u)}: {diag}'); print(diag,flush=True)
            if diag in ('HTTP 403','HTTP 429'): bloqueadas.add(loja(u))
        else: validados.add(u)
        for o in ofertas:
            k=chave(o)
            rank=lambda x:(x['preco'] is None,x['status']!='Em estoque',x['preco'] or float('inf'))
            if k not in resultados or rank(o)<rank(resultados[k]): resultados[k]=o
        time.sleep(1)
    h['links']=list(dict.fromkeys(h.get('links',[])+sorted(validados-set(fixos))))[-20:]
    linhas=[cfg['nome']+f' — buscas respondidas: {ok}/3']
    for o in resultados.values():
        acao=registrar(o,h.setdefault('ofertas',{}),cfg)
        falhas+=acao=='falha Telegram'
        linha=f"{o['loja']}: {o['status']} | "+(f"R$ {o['preco']:.2f}" if o['preco'] is not None else 'preço não confirmado')+f" | {acao}"
        print(linha,flush=True); linhas.append(linha)
        salvar(cache)
    if not resultados: linhas.append('Nenhuma oferta validada; estoque desconhecido.')
    return linhas+erros, len(resultados), falhas


def main():
    print('Monitor v7.0 — somente ofertas',flush=True)
    configs=carregar_produtos()
    cache=json.loads(ARQUIVO.read_text(encoding='utf-8')) if ARQUIVO.exists() else {}
    if not isinstance(cache,dict): raise ValueError('Histórico inválido')
    todos=cache.setdefault('_v4_produtos',{})
    # Migra estados da v3 sem apagar o histórico original.
    if 'dualsense-gta6-preto' not in todos:
        antigos={}
        for k,v in cache.items():
            if k.startswith('1000056977|') and isinstance(v,dict):
                estado=dict(v); preco=estado.get('preco'); status=estado.get('status')
                estado['elegivel']=isinstance(preco,(int,float)) and preco<=800 and status in ('Em estoque','Sem estoque','Pré-venda','Sob encomenda','Disponibilidade limitada')
                antigos[k.split('|',1)[1]]=estado
        todos['dualsense-gta6-preto']={'ofertas':antigos,'links':cache.get('_links',[])}
    teste=os.getenv('TESTE_TELEGRAM','').lower()=='true'
    agora=datetime.now(ZoneInfo('America/Sao_Paulo'))
    slot=agora.strftime('%Y-%m-%d %H')
    buscar=False  # Telegram agora usa webhook
    configs=[c for c in configs if c.get('ativo',True)]
    if not (teste or buscar or cache.get('_v5_hora')!=slot):
        salvar(cache); print('Comandos processados; busca horária já realizada.'); return
    linhas=[]; total=0; falhas=0
    for cfg in configs:
        h=todos.setdefault(cfg['id'],{})
        l,n,f=monitorar(cfg,h,cache); linhas.extend(l); total+=n; falhas+=f
        salvar(cache)
    cache['_v5_hora']=slot
    cache['_v5_status']={'hora':agora.isoformat(),'linhas':linhas,'total':total}
    dia=agora.date().isoformat()
    if teste or (agora.hour>=8 and cache.get('_v4_resumo')!=dia):
        texto='📋 Relatório Friday v7.0\n'+('\n'.join(linhas) if linhas else 'Nenhum produto ativo.')+'\nFalha de consulta não significa falta de estoque.'
        partes=[]
        while texto:
            partes.append(texto[:3500]); texto=texto[3500:]
        enviados=[telegram(parte) for parte in partes]
        if all(enviados):
            if not teste: cache['_v4_resumo']=dia
        else: falhas+=1
    salvar(cache)
    print('Produtos ativos:',len(configs),'| Ofertas verificadas:',total,flush=True)
    if not total and configs: print('::warning::Nenhuma oferta validada; estoque desconhecido.')
    if falhas: raise SystemExit(1)

if __name__=='__main__': main()
