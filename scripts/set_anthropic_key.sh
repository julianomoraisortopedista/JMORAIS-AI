#!/bin/zsh
# Saves the Anthropic API key currently in the clipboard to the macOS Keychain.
# Run it yourself after clicking "Copy" on a new key at platform.claude.com.
# The key is never printed or written to a file; the clipboard is cleared at the end.
set -u
key="$(pbpaste)"
key="${key//[[:space:]]/}"
if [[ "$key" != sk-ant-* ]]; then
  echo "A área de transferência não contém uma chave da Anthropic (deve começar com sk-ant-)."
  echo "Clique em Copy na chave em platform.claude.com e rode de novo."
  exit 1
fi
if ! security add-generic-password -U -a "$USER" -s anthropic-api-key -w "$key" >/dev/null 2>&1; then
  echo "Não foi possível gravar no Chaves (Keychain). Desbloqueie o Mac e tente de novo."
  exit 1
fi
unset key
pbcopy </dev/null
line='export ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s anthropic-api-key -w 2>/dev/null)"'
grep -qxF "$line" ~/.zshrc 2>/dev/null || echo "$line" >> ~/.zshrc
echo "OK: chave guardada no Chaves do Mac e área de transferência limpa."
echo "Feche este Terminal e abra um novo para usar o Claude."
