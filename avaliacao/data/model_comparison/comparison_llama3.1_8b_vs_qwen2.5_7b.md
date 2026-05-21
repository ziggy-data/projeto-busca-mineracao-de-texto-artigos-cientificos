# Relatório: Comparação de Modelos LLM

**Data:** 2026-05-19 03:23
**Documentos testados:** 30
**Configuração usada:** `num_predict=700` · `text_limit=3000ch` · `num_gpu=99` · `keep_alive=10m`

> ⚙️ Qualidade máxima preservada — `num_predict` e `text_limit` **não foram reduzidos**.
> As otimizações (`num_gpu`, `keep_alive`) são de infraestrutura e não afetam o output.

---

## 🏆 Recomendação Final

> ### Use **`llama3.1:8b`**
> *maior especificidade e menor taxa de erros*

```bash
# Comando para o corpus completo com o modelo recomendado:
python discourse_analysis.py --model llama3.1:8b --workers 3
```

> ⚠️ Configure o ollama para paralelismo antes de rodar:
> ```powershell
> $env:OLLAMA_NUM_PARALLEL=3; ollama serve
> ```

---

## Tabela comparativa

| Métrica | `llama3.1:8b` | `qwen2.5:7b` | Melhor |
|---|---|---|---|
| **Confiabilidade** | | | |
| Erros totais | 0 | 30 | **llama3.1:8b** |
| JSON inválido | 0/30 (0%) | 30/30 (100%) | **llama3.1:8b** |
| Timeouts | 0 | 0 | — |
| Docs sem claims | 25/30 (83%) | 0/30 (0%) | **qwen2.5:7b** |
| **Qualidade** | | | |
| Itens específicos/doc | 1.8 | 0.0 | **llama3.1:8b** |
| Itens genéricos/doc | 0.0 | 0.0 | **qwen2.5:7b** |
| % genérico | 0% | 0% | — |
| Campos preenchidos/doc | 0.6/4 | 0.0/4 | **llama3.1:8b** |
| Keywords específicas/doc | 4.8 | 0.0 | **llama3.1:8b** |
| Tipo retórico correto | 28/30 (93%) | 0/30 (0%) | **llama3.1:8b** |
| **Performance** | | | |
| Tempo médio/request | 4.6s | 0.0s | **qwen2.5:7b** |
| Tokens/segundo | 78 tok/s | 0 tok/s | **llama3.1:8b** |
| Estimativa corpus (workers=3) | ~0.8h | ~0.0h | **qwen2.5:7b** |

---

## Análise por campo

| Campo | `llama3.1:8b` (média/doc) | `qwen2.5:7b` (média/doc) | Melhor |
|---|---|---|---|
| claims | 0.7 | 0.0 | **llama3.1:8b** |
| contributions | 0.4 | 0.0 | **llama3.1:8b** |
| limitations | 0.4 | 0.0 | **llama3.1:8b** |
| future_work | 0.3 | 0.0 | **llama3.1:8b** |

---

## O que foi medido

- **Erros:** JSON inválido, resposta vazia, timeout (>150s), HTTP error
- **Genérico:** item com < 40 chars **ou** que contém frases como
  _"this chapter presents"_, _"future work will"_, _"os resultados mostram que o"_, etc.
- **Keywords válidas:** excluídas palavras como `results`, `methodology`, `analysis`, `simulation`

---

## Exemplos lado a lado (3 documentos)

### Documento 1
**Tese:** 
**Seção:** `Conclusões e considerações finais`

#### `llama3.1:8b`
- Tempo: **50.7s** | Tokens gerados: 318
- Específicos: **8** | Genéricos: **0** | Keywords válidas: **7**
- Tipo retórico: `Conclusion and final considerations` | Campos preenchidos: 4/4

**Claims específicos:**
> The Project PCO aimed to increase the capacity of use of the Operating Room without heavy investments in infrastructure and equipment.
> A work of adaptation of the data model for the software tool is necessary, including parametrization of data and definition of rules for sequencing, d

#### `qwen2.5:7b`
❌ **Erro:** `HTTP 404`


### Documento 2
**Tese:** 
**Seção:** `Novos Resultados`

#### `llama3.1:8b`
- Tempo: **3.1s** | Tokens gerados: 466
- Específicos: **0** | Genéricos: **0** | Keywords válidas: **5**
- Tipo retórico: `expository` | Campos preenchidos: 0/4

#### `qwen2.5:7b`
❌ **Erro:** `HTTP 404`


### Documento 3
**Tese:** A ideia para esse trabalho surgiu no período em que trabalhei no Insti
**Seção:** `Algumas considerações sobre os trabalhos revisados`

#### `llama3.1:8b`
- Tempo: **17.1s** | Tokens gerados: 408
- Específicos: **0** | Genéricos: **0** | Keywords válidas: **5**
- Tipo retórico: `problem statement` | Campos preenchidos: 0/4

#### `qwen2.5:7b`
❌ **Erro:** `HTTP 404`


---

## Configuração do teste

```python
QUALITY_OPTIONS = {
    "num_predict": 700,   # ← NÃO REDUZIDO — permite resposta JSON completa
    "num_ctx":     2048,  # ← suficiente para o prompt sem afetar output
    "num_gpu":     99,    # ← todos os layers na GPU (sem custo de qualidade)
    "keep_alive":  "10m", # ← mantém modelo carregado (sem custo de qualidade)
    "temperature": 0.1,
    "top_p":       0.9,
}
TEXT_LIMIT = 3000  # ← NÃO REDUZIDO — contexto completo da seção
```

_Gerado por `compare_models.py`_
