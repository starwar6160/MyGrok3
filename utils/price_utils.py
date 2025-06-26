from flask import Blueprint, jsonify
from MyGrok3.cost_calculator import initialize_prices
from MyGrok3 import logging_config

logger = logging_config.configure_logger(__name__)

price_api = Blueprint('price_api', __name__)

@price_api.route('/api/refresh-prices', methods=['POST'])
def refresh_prices_endpoint():
    """
    API endpoint to manually trigger a refresh of the model price list.
    """
    try:
        logger.info("Force refresh of prices triggered via API.")
        initialize_prices(force_refresh=True)
        return jsonify(success=True, message="Prices refreshed successfully."), 200
    except Exception as e:
        logger.error(f"Error during manual price refresh: {e}", exc_info=True)
        return jsonify(success=False, message="Failed to refresh prices."), 500
