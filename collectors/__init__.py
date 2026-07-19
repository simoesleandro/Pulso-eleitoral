# Pacote de Coletores do Pulso Eleitoral

from .datafolha import DatafolhaCollector
from .quaest import QuaestCollector
from .gazetadopovo import GazetaDoPovoColetor
from .atlas import AtlasCollector
from .poder360 import Poder360Collector
from .verita import VeritaCollector
from .cnn_brasil import CnnBrasilColetor
from .quaest_regional import QuaestRegionalColetor
from .paraná_pesquisas import ParanaPesquisasCollector

# Lista com todas as classes de coletores concretos para fácil iteração.
# ParanaPesquisasCollector (governador RJ via PDF) foi validado ao vivo em
# 2026-07-10 (extração limpa, sem contaminação de senador) e entrou na rotação.
ALL_COLLECTORS = [
    DatafolhaCollector,
    QuaestCollector,
    GazetaDoPovoColetor,
    AtlasCollector,
    Poder360Collector,
    VeritaCollector,
    CnnBrasilColetor,
    QuaestRegionalColetor,
    ParanaPesquisasCollector,
]
