"""Nine valid small ERP portfolios."""
from .portfolio_builder import PortfolioSize, build_portfolio
SMALL_SCENARIOS = {f"S{i:02d}": build_portfolio(f"S{i:02d}", "small", i - 1, PortfolioSize(12 + i % 5, 6 + i % 3, 20 + i % 6, 10 + i % 5, 14 + i % 8, ("1010", "2020"))) for i in range(1, 10)}
