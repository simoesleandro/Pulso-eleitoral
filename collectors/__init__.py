# Pacote de Coletores do Pulso Eleitoral

from .datafolha import DatafolhaCollector
from .quaest import QuaestCollector
from .atlas import AtlasCollector
from .poder360 import Poder360Collector
from .verita import VeritaCollector
from .cnn_brasil import CnnBrasilColetor
from .quaest_regional import QuaestRegionalColetor

# Lista com todas as classes de coletores concretos para fácil iteração.
# ParanaPesquisasCollector (collectors/paraná_pesquisas.py) já está implementado
# (pipeline de PDF → extrair_governador_rj), mas fica FORA desta lista até uma
# validação ao vivo do prompt de governador RJ contra um PDF real. Para ativar:
# importe-o acima e adicione à lista.
ALL_COLLECTORS = [
    DatafolhaCollector,
    QuaestCollector,
    AtlasCollector,
    Poder360Collector,
    VeritaCollector,
    CnnBrasilColetor,
    QuaestRegionalColetor,
]
