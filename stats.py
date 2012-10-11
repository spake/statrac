import httplib
import urllib
import re
import datetime

def get_probs_stats(html_data):
    # maps id to (name, status)
    setNames = {}
    sets = {}

    setPattern = re.compile('class="expfirst"><a name="(.*?)">(.*?)</a>')
    setResults = setPattern.findall(html_data)
    for m in setResults:
        setNames[m[0]] = [m[1], True]
        sets[m[0]] = []

    # get all problems
    probPattern = re.compile('problem.pl\?set=(.*?)\&problemid=(.*?)">(.*?)</a></td><td class="exp">(.*?)</td>')
    probResults = probPattern.findall(html_data)

    # maps id to (name, result, solve_date)
    problems = {}

    scoreRe = re.compile('([0-9]+)%')
    dateRe = re.compile('Finished on (.*?),')

    for m in probResults:
        setid = m[0]
        probid = int(m[1])
        prob_name = m[2].replace('&#39;',"'")
        status = m[3]

        #problems[probid] = [prob_name, status]
        sets[setid].append(probid)
        #if "Finished" not in status:
        #    setNames[setid][1] = False
        if status.startswith("Finished"):
            result = 100
            solve_date = datetime.datetime.strptime(dateRe.match(status).group(1), '%a %d %b %Y').date()
        elif status.startswith("New") or status.startswith("Viewed"):
            result = 0
            solve_date = None
        else:
            # get percentage
            result = int(scoreRe.match(status).group(1))
            solve_date = None

        problems[probid] = (prob_name, result, solve_date)

    return problems

def fetch_stats(username, password):
    params = {'login_username': username, 'login_password': password, 'login_submit': 'Log in'}

    conn = httplib.HTTPConnection('orac.amt.edu.au')
    conn.request('POST', '/cgi-bin/train/index.pl', urllib.urlencode(params))
    res = conn.getresponse()
    if res.status == 302:
        # extract cookies
        cookie_header = res.getheader('set-cookie')
        cookie = '; '.join(re.findall('(aioc_.*?=.*?);', cookie_header))
        result = True
    else:
        result = False
    conn.close()

    if result:
        # use the cookie, luke
        conn = httplib.HTTPConnection('orac.amt.edu.au')
        conn.request('GET', '/cgi-bin/train/hub.pl?expand=all', None, {'Cookie': cookie})
        res = conn.getresponse()
        if res.status == 200:
            result = res.read()
        else:
            result = False

    return result
