# Fase 2 — Extração Estrutural + Mapeamento DoCO

## Visão geral

```
data/pdfs/*.pdf
      ↓  [GROBID]
data/tei/*.tei.xml        ← XML TEI com estrutura do documento
      ↓  [tei_to_doco.py]
data/rdf/*.ttl            ← RDF/Turtle anotado com DoCO
      ↓  [Fase 3]
Apache Jena Fuseki        ← triplestore para SPARQL
```

## Setup

```bash
pip install -r requirements.txt
```

## Passo a passo

### 2A — Subir o GROBID

```bash
python grobid_setup.py
```

Sobe um container Docker com GROBID em `http://localhost:8070`.
Na primeira vez faz o pull da imagem (~2GB). Nas próximas vezes é instantâneo.

Para parar: `python grobid_setup.py --stop`

### 2B — Processar PDFs → TEI XML

```bash
# Teste com 5 PDFs
python process_pdfs.py --limit 5

# Corpus completo (pode demorar ~30-60min para 500+ PDFs)
python process_pdfs.py
```

Cada PDF gera um arquivo `data/tei/<handle>.tei.xml` com:
- Título, autores, afiliações
- Abstract
- Seções (com hierarquia)
- Parágrafos
- Referências bibliográficas

### 2C — Converter TEI → DoCO RDF

```bash
# Teste com 5 docs
python tei_to_doco.py --limit 5

# Corpus completo
python tei_to_doco.py
```

Cada documento gera um arquivo `data/rdf/<handle>.ttl` com triplas como:

```turtle
:11422_1234 a fabio:MastersThesis ;
    dcterms:title "Título da dissertação" ;
    po:contains :11422_1234_abstract,
                :11422_1234_sec_0,
                :11422_1234_sec_1 .

:11422_1234_sec_0 a deo:Introduction, doco:Section ;
    dcterms:title "Introdução" ;
    po:contains :11422_1234_sec_0_para_0 .

:11422_1234_sec_0_para_0 a doco:Paragraph ;
    c4o:hasContent "Nos últimos anos..." .
```

## Ontologias usadas (pacote SPAR)

| Prefixo | Ontologia | Uso |
|---|---|---|
| `doco:` | Document Components Ontology | Estrutura física (Seção, Parágrafo, Abstract) |
| `deo:` | Discourse Elements Ontology | Retórica (Introdução, Conclusão, Métodos) |
| `c4o:` | Citation Counting Ontology | Conteúdo textual dos componentes |
| `fabio:` | FRBR-aligned Bibliographic Ontology | Tipo do documento (Thesis, Article) |
| `po:` | Document Structural Patterns | Relações estruturais (contains, isPartOf) |
| `bibo:` | Bibliographic Ontology | Referências bibliográficas |

## Tipos retóricos inferidos automaticamente

| Título de seção contém | Tipo DoCO/DEO |
|---|---|
| "introduç", "introduc" | `deo:Introduction` |
| "conclus", "considera" | `deo:Conclusion` |
| "method", "metodolog" | `deo:Methods` |
| "related", "literatura", "revisão" | `deo:RelatedWork` |
| "experiment", "result", "avalia" | `deo:Results` |
| "discuss", "análise" | `deo:Discussion` |
| "background", "fundament" | `deo:Background` |
| "referenc", "bibliograf" | `doco:ListOfReferences` |
| outros | `doco:Section` (genérico) |

## Dicas de performance

- GROBID usa modelos de deep learning — recomendo deixar rodando em background
- `--workers 2` é o padrão seguro; aumente para 3-4 se a CPU não estiver sobrecarregada  
- Para o corpus completo (~500 docs), espere ~1-2 horas
- O processamento é idempotente: pode interromper e retomar a qualquer momento
