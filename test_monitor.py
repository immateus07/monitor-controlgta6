import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
import monitor as m

class TestFriday(unittest.TestCase):
    def test_cadastro(self):
        c=[]; h={}
        for x in ['➕ Adicionar produto','SSD Samsung 990 PRO 1TB','650','-','Samsung, 990 PRO, 1TB']:
            r,changed,b,k=m.guiado(x,c,h)
        self.assertTrue(changed); self.assertEqual(c[0]['preco_maximo'],650)
        self.assertEqual(len(c),1)
        ident=c[0]['id']
        for x in ['💰 Alterar preço',c[0]['nome']+' | '+ident,'800']:
            m.guiado(x,c,h)
        self.assertEqual(c[0]['preco_maximo'],800)
        for x in ['⏸️ Pausar',ident]: m.guiado(x,c,h)
        self.assertFalse(c[0]['ativo'])
        for x in ['▶️ Ativar',ident]: m.guiado(x,c,h)
        self.assertTrue(c[0]['ativo'])
        for x in ['🗑️ Remover',ident,'Cancelar']: m.guiado(x,c,h)
        self.assertEqual(len(c),1)
        for x in ['🗑️ Remover',ident,'SIM']: m.guiado(x,c,h)
        self.assertEqual(c,[])
    def test_duplicidade(self):
        h={}; cfg={'nome':'Controle','preco_maximo':800,'avisar_sem_estoque':True}
        o={'loja':'KaBuM','vendedor':'KaBuM','preco':599,'status':'Sem estoque','url':'https://www.kabum.com.br/produto/1'}
        with patch.object(m,'telegram',return_value=True) as tg:
            self.assertEqual(m.registrar(o,h,cfg),'notificado')
            self.assertEqual(m.registrar(o,h,cfg),'duplicado ignorado')
            o.update(preco=800,status='Em estoque'); self.assertEqual(m.registrar(o,h,cfg),'notificado')
            o['preco']=801; self.assertIn('fora do filtro',m.registrar(o,h,cfg)); self.assertEqual(tg.call_count,2)
    def test_amazon_sem_preco(self):
        soup=BeautifulSoup('<span id="productTitle">DualSense</span><div id="availability">Indisponível</div>','html.parser')
        self.assertEqual(list(m.extrair(soup,'https://www.amazon.com.br/dp/B0HHNVBHQ5',{'termos_obrigatorios':['dualsense']})),[])
    def test_microdata(self):
        html='''<div itemscope itemtype="https://schema.org/Product"><span itemprop="name">DualSense preto</span><div itemscope itemtype="https://schema.org/Offer"><meta itemprop="price" content="599"><meta itemprop="priceCurrency" content="BRL"><link itemprop="availability" href="https://schema.org/OutOfStock"></div></div>'''
        o=list(m.extrair(BeautifulSoup(html,'html.parser'),'https://www.magazineluiza.com.br/produto/p/123',{'termos_obrigatorios':['dualsense','preto']}))
        self.assertEqual(o[0]['preco'],599); self.assertEqual(o[0]['status'],'Sem estoque')
    def test_magalu(self):
        self.assertFalse(m.pagina_produto('https://www.magazineluiza.com.br/busca/controle/'))
        self.assertTrue(m.pagina_produto('https://www.magazineluiza.com.br/controle/p/123/'))
    def test_menu(self):
        self.assertTrue(m.guiado('🔎 Buscar agora',[],{})[2]); self.assertIn('keyboard',m.guiado('/menu',[],{})[3])
if __name__=='__main__': unittest.main()
