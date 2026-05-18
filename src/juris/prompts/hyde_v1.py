"""HyDE (Hypothetical Document Embeddings) prompt templates."""

PROMPT_VERSION = "hyde_v1"

SYSTEM_PROMPT = (
    "Voce e um assistente juridico que escreve ementas hipoteticas "
    "no estilo do STJ/STF para auxiliar pesquisa de jurisprudencia."
)

EXPAND_PROMPT = (
    "Tese a ser pesquisada:\n"
    "{query}\n\n"
    "Escreva UMA ementa hipotetica curta (60-100 palavras) no estilo de uma decisao "
    "do STJ que SUSTENTE essa tese. Use vocabulario e estrutura tipicos: comecar com "
    "o tema, expor a tese vencedora, citar dispositivo legal relevante. Nao invente "
    "numeros de processo, ministros ou sumulas — escreva apenas o corpo da ementa.\n\n"
    "Ementa hipotetica:"
)
