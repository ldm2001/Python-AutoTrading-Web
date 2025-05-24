import requests
import json
import datetime
import time
import yaml
import traceback
import chromedriver_autoinstaller
from flask import Flask, render_template
from selenium import webdriver
from flask_socketio import SocketIO
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from flask_cors import CORS
from threading import Lock

# 셀레니움 크롬 드라이버 자동 설치 및 헤드리스 옵션 적용 
chromedriver_autoinstaller.install()
options = webdriver.ChromeOptions()
options.add_argument("headless")
driver = webdriver = webdriver.Chrome(options=options)

# 주식, 인덱스, 뉴스, 관심 종목 코드 리스트 등 글로벌 변수
stockList = []
indexChart = []
news = []
symbol_list = ["005930", "066570", "005380", "000660"]  # (삼성전자, LG전자, 현대차, SK하이닉스)

# 네이버 주식 페이지에서 실시간 주가 및 정보 크롤링 함수 
def getPrice(stock):
    driver.get("https://m.stock.naver.com/search")
    sb = driver.find_element(By.XPATH, '//*[@id="__next"]/div[1]/div/div/div/div/input[1]')
    time.sleep(1)
    sb.send_keys(stock)
    sb.send_keys(Keys.ENTER)
    time.sleep(3)
    driver.find_element(By.XPATH, '//*[@id="content"]/div[2]/ul/li[1]/button').click()
    time.sleep(5.5)
    code = driver.find_element(By.XPATH, '//div[@id="content"]/div[@id="stockContentWrapper"]/div[3]/div[1]/div[1]/span[1]').text
    price = driver.find_element(By.XPATH, '//div[@id="content"]/div[@id="stockContentWrapper"]/div[3]/div[1]/div[1]/strong').text.replace("원", '').replace("USD", "")
    chart = driver.find_element(By.CLASS_NAME, 'GraphMain_stockChart__gQeN3').get_attribute('src')
    table = driver.find_element(By.CLASS_NAME, 'StockInfo_list__V96U6')
    volume = table.find_element(By.CSS_SELECTOR, 'ul > li:nth-child(5) > div > span').text
    total = table.find_element(By.CSS_SELECTOR, 'ul > li:nth-child(7) > div > span').text.split('\n')[0].replace("USD", "")
    img_link = ""
    for elem in driver.find_elements(By.CLASS_NAME, 'VLayoutCard_article__utIMG'):
        if elem.text[0:6]=="주주 오픈톡":
            img_link = elem.find_element(By.TAG_NAME, "img").get_attribute("src")

    return [stock, code, price, volume, total, img_link, chart]

# 플라스크 웹서버 및 CORS, SocketIO 설정 
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# YAML 환경설정 파일에서 키 및 환경 변수 읽기 
with open('config.yaml', encoding='UTF-8') as f:
    _cfg = yaml.load(f, Loader=yaml.FullLoader)
APP_KEY = _cfg['APP_KEY']
APP_SECRET = _cfg['APP_SECRET']
ACCESS_TOKEN = ""
CANO = _cfg['CANO']
ACNT_PRDT_CD = _cfg['ACNT_PRDT_CD']
DISCORD_WEBHOOK_URL = _cfg['DISCORD_WEBHOOK_URL']
URL_BASE = _cfg['URL_BASE']

# 디스코드 및 메시지 전송 함수 
def send_message(msg):
    now = datetime.datetime.now()
    message = {"content": f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {str(msg)}"}
    requests.post(DISCORD_WEBHOOK_URL, data=message)
    socketio.emit("message", message["content"])
    print(message)

# OpenAPI 토큰 획득 함수 
def get_access_token():
    headers = {"content-type": "application/json"}
    body = {"grant_type": "client_credentials",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET}
    PATH = "oauth2/tokenP"
    URL = f"{URL_BASE}/{PATH}"
    res = requests.post(URL, headers=headers, data=json.dumps(body))
    ACCESS_TOKEN = res.json()["access_token"]
    print("액세스 토큰 : " + ACCESS_TOKEN)
    return ACCESS_TOKEN

# OpenAPI 전용 해시키 생성 함수 (매수/매도 요청시 사용) 
def hashkey(datas):
    PATH = "uapi/hashkey"
    URL = f"{URL_BASE}/{PATH}"
    headers = {
        'content-Type': 'application/json',
        'appKey': APP_KEY,
        'appSecret': APP_SECRET,
    }
    res = requests.post(URL, headers=headers, data=json.dumps(datas))
    hashkey = res.json()["HASH"]
    return hashkey

# 특정 종목 현재가 조회
def get_current_price(code="005930"):
    PATH = "uapi/domestic-stock/v1/quotations/inquire-price"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type": "application/json",
               "authorization": f"Bearer {ACCESS_TOKEN}",
               "appKey": APP_KEY,
               "appSecret": APP_SECRET,
               "tr_id": "FHKST01010100"}
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code,
    }
    res = requests.get(URL, headers=headers, params=params)
    return int(res.json()['output']['stck_prpr'])

# 네이버 모바일에서 종목별 차트 이미지 URL 추출 
def get_chart(code="005930"):
    try:
        url = f"https://m.stock.naver.com/domestic/stock/{code}/total"
        driver.get(url)
        time.sleep(1)
        chart = driver.find_element(By.CLASS_NAME, 'GraphMain_stockChart__gQeN3').get_attribute('src')
        return chart
    except:
        return ''

# 네이버 모바일에서 주요 주가지수 차트 이미지 URL 추출 
def get_chart_index(code="KOSPI"):
    try:
        url = f"https://m.stock.naver.com/domestic/index/{code}/total"
        driver.get(url)
        time.sleep(1)
        chart = driver.find_element(By.CLASS_NAME, 'GraphMain_stockChart__gQeN3').get_attribute('src')
        return chart
    except:
        return ''

# 네이버 뉴스 기사 목록 추출 (HTML)
def get_naver_news():
    try:
        url = f"https://www.naver.com"
        driver.get(url)
        time.sleep(2)
        driver.find_element(By.XPATH, '//*[@id="newsstand"]/div[1]/div/ul/li[4]/a').click()
        time.sleep(2)
        element = driver.find_element(By.XPATH, '//*[@id="newsstand"]/div[3]')
        html_content = element.get_attribute('outerHTML')
        return html_content
    except:
        return ''

# 종목 목표가 계산 함수(시가+0.5*(전일고가-전일저가)) 
def get_target_price(code="005930"):
    PATH = "uapi/domestic-stock/v1/quotations/inquire-daily-price"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type": "application/json",
               "authorization": f"Bearer {ACCESS_TOKEN}",
               "appKey": APP_KEY,
               "appSecret": APP_SECRET,
               "tr_id": "FHKST01010400"}
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": code,
        "fid_org_adj_prc": "1",
        "fid_period_div_code": "D"
    }
    res = requests.get(URL, headers=headers, params=params)
    stck_oprc = int(res.json()['output'][0]['stck_oprc'])  # 오늘 시가
    stck_hgpr = int(res.json()['output'][1]['stck_hgpr'])  # 전일 고가
    stck_lwpr = int(res.json()['output'][1]['stck_lwpr'])  # 전일 저가
    target_price = stck_oprc + (stck_hgpr - stck_lwpr) * 0.5
    return target_price

# 보유 주식 현황(잔고, 평가금액 등) 조회 및 알림 
def get_stock_balance():
    PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type": "application/json",
               "authorization": f"Bearer {ACCESS_TOKEN}",
               "appKey": APP_KEY,
               "appSecret": APP_SECRET,
               "tr_id": "TTTC8434R",
               "custtype": "P",
               }
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    res = requests.get(URL, headers=headers, params=params)
    stock_list = res.json()['output1']
    evaluation = res.json()['output2']
    stock_dict = {}
    send_message(f"====보유잔고====")
    for stock in stock_list:
        if int(stock['hldg_qty']) > 0:
            stock_dict[stock['pdno']] = stock['hldg_qty']
            send_message(f"{stock['prdt_name']}({stock['pdno']}): {stock['hldg_qty']}주")
            time.sleep(0.1)
    send_message(f"주식 평가 금액: {evaluation[0]['scts_evlu_amt']}원")
    time.sleep(0.1)
    send_message(f"평가 손익 합계: {evaluation[0]['evlu_pfls_smtl_amt']}원")
    time.sleep(0.1)
    send_message(f"총 평가 금액: {evaluation[0]['tot_evlu_amt']}원")
    time.sleep(0.1)
    send_message(f"=================")
    return stock_dict

# 계좌 주문 가능 현금 잔고 조회 
def get_balance():
    PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
    URL = f"{URL_BASE}/{PATH}"
    headers = {"Content-Type": "application/json",
               "authorization": f"Bearer {ACCESS_TOKEN}",
               "appKey": APP_KEY,
               "appSecret": APP_SECRET,
               "tr_id": "TTTC8908R",
               "custtype": "P",
               }
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "PDNO": "005930",
        "ORD_UNPR": "65500",
        "ORD_DVSN": "01",
        "CMA_EVLU_AMT_ICLD_YN": "Y",
        "OVRS_ICLD_YN": "Y"
    }
    res = requests.get(URL, headers=headers, params=params)
    cash = res.json()['output']['ord_psbl_cash']
    send_message(f"주문 가능 현금 잔고: {cash}원")
    return int(cash)

# 매수 함수 (시장가 주문) 
def buy(code="005930", qty="1"):
    PATH = "uapi/domestic-stock/v1/trading/order-cash"
    URL = f"{URL_BASE}/{PATH}"
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "PDNO": code,
        "ORD_DVSN": "01",
        "ORD_QTY": str(int(qty)),
        "ORD_UNPR": "0",
    }
    headers = {"Content-Type": "application/json",
               "authorization": f"Bearer {ACCESS_TOKEN}",
               "appKey": APP_KEY,
               "appSecret": APP_SECRET,
               "tr_id": "TTTC0802U",
               "custtype": "P",
               "hashkey": hashkey(data)
               }
    res = requests.post(URL, headers=headers, data=json.dumps(data))
    if res.json()['rt_cd'] == '0':
        send_message(f"[매수 성공]{str(res.json())}")
        return True
    else:
        send_message(f"[매수 실패]{str(res.json())}")
        return False

# 시장 인덱스 현재가 조회 
def get_market_index(index_code="0001"):
    PATH = "uapi/domestic-stock/v1/quotations/inquire-index-price"
    URL = f"{URL_BASE}/{PATH}"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appKey": APP_KEY,
        "appSecret": APP_SECRET,
        "tr_id": "FHPUP02100000",
        "custtype" : "P"
    }
    params = {
        "fid_cond_mrkt_div_code": "U",
        "fid_input_iscd": index_code
    }
    res = requests.get(URL, headers=headers, params=params)
    return res.json()['output']['bstp_nmix_prpr']

# 매도 함수 (시장가 주문)
def sell(code="005930", qty="1"):
    PATH = "uapi/domestic-stock/v1/trading/order-cash"
    URL = f"{URL_BASE}/{PATH}"
    data = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "PDNO": code,
        "ORD_DVSN": "01",
        "ORD_QTY": qty,
        "ORD_UNPR": "0",
    }
    headers = {"Content-Type": "application/json",
               "authorization": f"Bearer {ACCESS_TOKEN}",
               "appKey": APP_KEY,
               "appSecret": APP_SECRET,
               "tr_id": "TTTC0801U",
               "custtype": "P",
               "hashkey": hashkey(data)
               }
    res = requests.post(URL, headers=headers, data=json.dumps(data))
    if res.json()['rt_cd'] == '0':
        send_message(f"[매도 성공]{str(res.json())}")
        return True
    else:
        send_message(f"[매도 실패]{str(res.json())}")
        return False

# 메인 자동매매 루프 함수 (시작~종료)
def tradeMain():
    try:
        bought_list = []
        total_cash = get_balance()
        stock_dict = get_stock_balance()
        for sym in stock_dict.keys():
            bought_list.append(sym)
        target_buy_count = 3
        buy_percent = 0.33
        buy_amount = total_cash * buy_percent
        soldout = False

        send_message("===자동매매 프로그램을 시작합니다===")
        while True:
            t_now = datetime.datetime.now()
            t_9 = t_now.replace(hour=9, minute=0, second=0, microsecond=0)
            t_start = t_now.replace(hour=9, minute=5, second=0, microsecond=0)
            t_sell = t_now.replace(hour=15, minute=15, second=0, microsecond=0)
            t_exit = t_now.replace(hour=15, minute=20, second=0, microsecond=0)
            today = datetime.datetime.today().weekday()
            if today == 5 or today == 6:
                send_message("주말이므로 프로그램을 종료합니다.")
                break
            if t_9 < t_now < t_start and soldout == False:  # 잔여 수량 매도
                for sym, qty in stock_dict.items():
                    sell(sym, qty)
                soldout == True
                bought_list = []
                stock_dict = get_stock_balance()
            if t_start < t_now < t_sell:
                for sym in symbol_list:
                    if len(bought_list) < target_buy_count:
                        if sym in bought_list:
                            continue
                        target_price = get_target_price(sym)
                        current_price = get_current_price(sym)
                        if target_price < current_price:
                            buy_qty = 0
                            buy_qty = int(buy_amount // current_price)
                            if buy_qty > 0:
                                send_message(f"{sym} 목표가 달성({target_price} < {current_price}) 매수를 시도합니다.")
                                result = buy(sym, buy_qty)
                                if result:
                                    soldout = False
                                    bought_list.append(sym)
                                    get_stock_balance()
                        time.sleep(1)
                time.sleep(1)
                if t_now.minute == 30 and t_now.second <= 5:
                    get_stock_balance()
                    time.sleep(5)
            if t_sell < t_now < t_exit:
                if soldout == False:
                    stock_dict = get_stock_balance()
                    for sym, qty in stock_dict.items():
                        sell(sym, qty)
                    soldout = True
                    bought_list = []
                    time.sleep(1)
            if t_exit < t_now:
                send_message("프로그램을 종료합니다.")
                break
    except Exception as e:
        send_message(f"[오류 발생]{e}")
        time.sleep(1)

# 소켓 명령 이벤트 핸들러 (백그라운드 실행)
@socketio.on("command")
def handle_command(data):
    print("Received command: " + data)
    socketio.emit("message", "CONNECTED")
    socketio.start_background_task(tradeMain)

# 플라스크 기본 라우트(index.html 페이지) 
@app.route('/')
def home():
    return render_template('index.html', stockList=stockList, indexChart=indexChart, news=news)

# Test
@app.route("/test")
def test():
    socketio.emit("message", "Hello World")
    return ""

# 소켓이 업데이트를 요청하면 백그라운드 업데이트 태스크 실행 
@socketio.on("start_updates")
def handle_start_updates():
    global update_task_running
    print("Client requested updates")
    with update_task_lock:
        if not update_task_running:
            update_task_running = True
            socketio.start_background_task(send_updates)
        else:
            print("Update task is already running")

# 실시간 주가, 지수, 뉴스 데이터 전송 루프 (5분마다 업데이트) 
def send_updates():
    global update_task_running
    try:
        index_list = ["0001", "1001", "2001", "2007"] # 코스피, 코스닥, 코스피200, 코스피100
        index2_list = ["KOSPI", "KOSDAQ", "KPI200", "KPI100"]
        last_print_time = datetime.datetime.now()

        chart_list = []
        index_chart_list = []
        news = []

        switch = True

        while True:
            # 현재 시간
            current_time = datetime.datetime.now()
            price_list = []
            index_value_list = []
            
            for sym in symbol_list:
                price_list.append(f"{get_current_price(sym):,}")

            for idx in index_list:
                index_value_list.append(get_market_index(idx))
            
            # 5분이 경과했는지 확인하여 차트/뉴스 갱신
            if (current_time - last_print_time).seconds >= 300:
                for index, sym in enumerate(symbol_list):
                    temp = get_chart(sym)
                    if switch:
                        if temp:
                            chart_list.append(temp)
                    else:
                        if temp:
                            chart_list[index] = temp
                for index, idx in enumerate(index2_list):
                    temp = get_chart_index(idx)
                    if switch:
                        if temp:
                            index_chart_list.append(temp)
                    else:
                        if temp:
                            index_chart_list[index] = temp
                temp = get_naver_news()
                if switch:
                    if temp:
                        news.append(temp)
                else:
                    if temp:
                        news[0] = temp
                # 마지막 출력 시간을 현재 시간으로 갱신
                last_print_time = current_time
                switch = False
            
            data = {
                "stock": price_list,
                "chart": chart_list,
                "stock_index": index_value_list,
                "stock_index_chart": index_chart_list,
                "news": news
            }
            
            socketio.emit("update", data)
            print("가격 전송 완료")
            time.sleep(0.3)

    except Exception as e:
        print(f"Error in send_updates: {e}")
        traceback.print_exc()
    finally:
        with update_task_lock:
            update_task_running = False

# 초기 데이터 로딩 및 서버 구동 
if __name__ == '__main__':
    update_task_running = False
    update_task_lock = Lock()
    ACCESS_TOKEN = get_access_token()
    print("Getting Stock Information...")
    stockList.append(getPrice("삼성전자"))
    stockList.append(getPrice("LG전자"))
    stockList.append(getPrice("현대차"))
    stockList.append(getPrice("SK하이닉스"))
    indexChart.append(get_chart_index("KOSPI"))
    indexChart.append(get_chart_index("KOSDAQ"))
    indexChart.append(get_chart_index("KPI200"))
    indexChart.append(get_chart_index("KPI100"))
    news.append(get_naver_news())
    print("Done")
    socketio.run(app, debug=False, allow_unsafe_werkzeug=True, port=5001, log_output=True)
    