from aiogram.fsm.state import State, StatesGroup

class UserStates(StatesGroup):
    waiting_for_subscriber_video = State()
    waiting_for_report = State()
    
    # Состояния для административных инструментов
    waiting_for_reklama_content = State()
    waiting_for_broadcast_content = State()