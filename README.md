# Sebo Store - Forra Cultural

Catálogo online de um sebo de Belém - PA. Funciona como vitrine e e-commerce simplificado: o cliente navega o acervo, monta o carrinho e finaliza a compra pelo WhatsApp do vendedor.

![capa do site](static/img/capa.png)

## Tecnologias

Python · Flask · SQLite · HTML / CSS / JavaScript · OpenAI (gpt-4o-mini com vision) · Pillow · Gunicorn

## Funcionalidades

**Site público**

- Home com hero, carrosséis temáticos por gênero e coleções curadas, e destaque rotativo de livros
- Catálogo com busca por título / autor e filtro por gênero
- Página de detalhe com recomendação automática de títulos semelhantes
- Carrinho persistido no navegador e checkout que abre o WhatsApp com o pedido já formatado

**Painel administrativo**

- Cadastro de livros com upload de capa e **identificação automática por IA** a partir da imagem
- Compressão automática de imagens (reduz uploads de 2-3 MB para ~150 KB)
- Gestão de coleções curadas (criar, editar, reordenar, remover)
- Acompanhamento de pedidos com filtro por status
- Dashboard com estatísticas (livros, pedidos, receita)