"""Eight valid large ERP portfolios sized for classroom computers."""
from .portfolio_builder import PortfolioSize, build_portfolio
LARGE_SCENARIOS = {f"L{i:02d}": build_portfolio(f"L{i:02d}", "large", 16 + i, PortfolioSize(210 + i * 12, 44 + i * 2, 155 + i * 8, 188 + i * 10, 390 + i * 35, ("1010", "2020", "3030", "4040"))) for i in range(1, 9)}
