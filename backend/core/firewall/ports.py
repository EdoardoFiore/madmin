"""
Port specifications as iptables accepts them, parsed once for every consumer
(model validation, rule building, conntrack matching).

  "443"            single port      -> --dport 443
  "8000:8080"      range, low<high  -> --dport 8000:8080
  "80,443,8000:8080"  list          -> -m multiport --dports (max 15 ports,
                                       a range counts as two)

Anything else is rejected here: iptables-restore would reject the whole
ruleset for one bad line, not just that rule.
"""
from typing import List, Optional, Tuple

MULTIPORT_MAX = 15


def parse_port_spec(spec) -> List[Tuple[int, int]]:
    """[(low, high), ...]; raises ValueError on anything iptables would refuse."""
    text = str(spec)
    if not text:
        raise ValueError("Porta vuota")
    items: List[Tuple[int, int]] = []
    weight = 0
    for token in text.split(","):
        bounds = token.split(":")
        if len(bounds) > 2 or not all(b.isascii() and b.isdigit() and len(b) <= 5 for b in bounds):
            raise ValueError(f"Porta non valida: {token}")
        low, high = int(bounds[0]), int(bounds[-1])
        if not (1 <= low <= 65535 and 1 <= high <= 65535):
            raise ValueError(f"Porta non valida: {token} (range 1-65535)")
        if len(bounds) == 2 and low >= high:
            raise ValueError(f"Intervallo di porte non valido: {token} (il primo valore deve essere minore)")
        items.append((low, high))
        weight += 2 if len(bounds) == 2 else 1
    if len(items) > 1 and weight > MULTIPORT_MAX:
        raise ValueError(
            f"Troppe porte: massimo {MULTIPORT_MAX} in un elenco (un intervallo conta 2)"
        )
    return items


def port_in_spec(port: int, spec: Optional[str]) -> bool:
    """True when `spec` is empty (any port) or covers `port`."""
    if not spec:
        return True
    return any(low <= port <= high for low, high in parse_port_spec(spec))
