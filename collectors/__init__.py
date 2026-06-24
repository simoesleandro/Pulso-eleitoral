# Pacote de Coletores do Pulso Eleitoral

from .datafolha import DatafolhaCollector
from .ibope import IbopeCollector
from .quaest import QuaestCollector
from .genial_quaest import GenialQuaestCollector
from .atlas import AtlasCollector
from .paraná_pesquisas import ParanaPesquisasCollector
from .real_time import RealTimeCollector
from .poder360 import Poder360Collector
from .verita import VeritaCollector
from .cnn_brasil import CnnBrasilColetor
from .quaest_regional import QuaestRegionalColetor

# Lista com todas as classes de coletores concretos para fácil iteração
ALL_COLLECTORS = [
    DatafolhaCollector,
    IbopeCollector,
    QuaestCollector,
    GenialQuaestCollector,
    AtlasCollector,
    ParanaPesquisasCollector,
    RealTimeCollector,
    Poder360Collector,
    VeritaCollector,
    CnnBrasilColetor,
    QuaestRegionalColetor,
]
