"""Eight valid medium ERP portfolios."""
from .portfolio_builder import PortfolioSize, build_portfolio
MEDIUM_SCENARIOS = {f"M{i:02d}": build_portfolio(f"M{i:02d}", "medium", 17 if i == 8 else 8 + i, PortfolioSize(58 + i * 4, 18 + i, 55 + i * 4, 48 + i * 3, 85 + i * 8, ("1010", "2020", "3030"))) for i in range(1, 9)}
