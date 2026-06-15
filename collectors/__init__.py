# Pacote de Coletores do Pulso Eleitoral

from .datafolha import DatafolhaCollector
from .ibope import IbopeCollector
from .quaest import QuaestCollector
from .genial_quaest import GenialQuaestCollector
from .atlas import AtlasCollector
from .paraná_pesquisas import ParanaPesquisasCollector
from .real_time import RealTimeCollector

# Lista com todas as classes de coletores concretos para fácil iteração
ALL_COLLECTORS = [
    DatafolhaCollector,
    IbopeCollector,
    QuaestCollector,
    GenialQuaestCollector,
    AtlasCollector,
    ParanaPesquisasCollector,
    RealTimeCollector
]
