# Orientações — projeto integrado (ADS), caso CAMC

Resolver o caso da CAMC. Não citar o PDF do enunciado e não colar aviso institucional ("Prezado aluno", "seja bem-vindo").
Texto em português, tom técnico, citação autor-data.

## Introdução
- A CAMC (mel puro, chia a granel, barra energética), o cenário rural e os gargalos: papel, planilhas soltas, logística, atendimento espalhado, sem métrica de feedback.
- Objetivo da modernização: rastreabilidade da colmeia/planta até a mesa.

## Desenvolvimento

### Passo 1: Projeto de software (CRM e backlog)
- Requisitos e CRM.
- Backlog: módulos (cadastro de clientes, atendimento multicanal, tickets, histórico de pedidos, rastreabilidade), RF e RNF com critério de aceitação em história de usuário.
- Quadro no estilo Kanban: A fazer, Em andamento, Revisão/testes, Concluído. Cartão com etiqueta e responsável.

### Passo 2: Segurança e auditoria
- Tríade CIA.
- RBAC da CAMC: Operador de Campo, Laboratório de Mel, Produção Industrial, Logística, Financeiro, Gestão/Auditoria.
- Backup: incremental diário, full semanal, regra 3-2-1, criptografia em repouso e em trânsito.
- Trilha de auditoria da pesagem até a entrega e o feedback.

### Passo 3: Redes
- Topologia física e lógica ligando o laboratório de beneficiamento do mel e a fábrica da barra energética.
- Enlace: VPN IPsec site-to-site, fibra ou rádio dedicado.
- Hardware: roteador, firewall UTM, switch gerenciável com VLAN, access point industrial.

### Passo 4: Interface
- IHC e heurísticas de Nielsen.
- Arquitetura da informação do wireframe de feedback no app.
- Fluxo em no máximo três cliques depois da entrega: nota, tags ou comentário, envio.
- Diagrama em texto da tela (cabeçalho, produto, estrelas, campo, botão).

### Passo 5: Arquitetura de computadores
- Subsistemas e tolerância a falhas.
- Servidor central: processador multinúcleo, RAM ECC, fonte redundante.
- Armazenamento em RAID (RAID 1 ou RAID 10, disco NVMe ou SAS) para o banco da CAMC.

## Conclusão
- Como as partes se encaixam nos gargalos da CAMC.
- Efeito em competitividade, na cadeia produtiva e na confiança de quem compra.
