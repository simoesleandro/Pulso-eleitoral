# Pacote de Coletores do Pulso Eleitoral

from .datafolha import DatafolhaCollector
from .quaest import QuaestCollector
from .atlas import AtlasCollector
from .poder360 import Poder360Collector
from .verita import VeritaCollector
from .cnn_brasil import CnnBrasilColetor
from .quaest_regional import QuaestRegionalColetor

# Lista com todas as classes de coletores concretos para fácil iteração.
# collectors/paraná_pesquisas.py não entra aqui: fetch() nunca foi
# implementado (sempre retorna []) e a classe não define _get_page — mesmo
# tratamento dado aos stubs mortos removidos (ibope, real_time, genial_quaest).
ALL_COLLECTORS = [
    DatafolhaCollector,
    QuaestCollector,
    AtlasCollector,
    Poder360Collector,
    VeritaCollector,
    CnnBrasilColetor,
    QuaestRegionalColetor,
]
