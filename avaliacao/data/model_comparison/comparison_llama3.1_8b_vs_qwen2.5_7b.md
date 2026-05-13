# Relatório: Comparação de Modelos LLM

**Data:** 2026-04-13 02:33
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
| Itens específicos/doc | 1.7 | 0.0 | **llama3.1:8b** |
| Itens genéricos/doc | 0.1 | 0.0 | **qwen2.5:7b** |
| % genérico | 2% | 0% | **qwen2.5:7b** |
| Campos preenchidos/doc | 0.8/4 | 0.0/4 | **llama3.1:8b** |
| Keywords específicas/doc | 3.6 | 0.0 | **llama3.1:8b** |
| Tipo retórico correto | 25/30 (83%) | 0/30 (0%) | **llama3.1:8b** |
| **Performance** | | | |
| Tempo médio/request | 6.3s | 2.0s | **qwen2.5:7b** |
| Tokens/segundo | 53 tok/s | 0 tok/s | **llama3.1:8b** |
| Estimativa corpus (workers=3) | ~1.2h | ~0.4h | **qwen2.5:7b** |

---

## Análise por campo

| Campo | `llama3.1:8b` (média/doc) | `qwen2.5:7b` (média/doc) | Melhor |
|---|---|---|---|
| claims | 0.6 | 0.0 | **llama3.1:8b** |
| contributions | 0.5 | 0.0 | **llama3.1:8b** |
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
- Tempo: **7.4s** | Tokens gerados: 432
- Específicos: **0** | Genéricos: **0** | Keywords válidas: **5**
- Tipo retórico: `conclusion` | Campos preenchidos: 0/4

#### `qwen2.5:7b`
❌ **Erro:** `HTTP 404`


### Documento 2
**Tese:** 
**Seção:** `Novos Resultados`

#### `llama3.1:8b`
- Tempo: **5.9s** | Tokens gerados: 298
- Específicos: **0** | Genéricos: **0** | Keywords válidas: **4**
- Tipo retórico: `expository` | Campos preenchidos: 0/4

#### `qwen2.5:7b`
❌ **Erro:** `HTTP 404`


### Documento 3
**Tese:** EFFECTS OF SINUSOIDAL ELECTRIC STIMULATION IN INDUCED BRAIN RESPONSES:
**Seção:** `CONCLUSÃO`

#### `llama3.1:8b`
- Tempo: **6.5s** | Tokens gerados: 333
- Específicos: **7** | Genéricos: **1** | Keywords válidas: **8**
- Tipo retórico: `Conclusion` | Campos preenchidos: 4/4

**Claims específicos:**
> Different profiles of induced brain responses were observed for sinusoidal electric stimulation at 5 Hz and 3 kHz, particularly in the intensity 1.2xL
> The study suggests a new alternative using ERD/ERS and EES in permanent regime for evaluating tactile and thermalgic submodalities of the somesthetic 

⚠️ **Claims genéricos (baixa qualidade):**
> None explicitly mentioned

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
