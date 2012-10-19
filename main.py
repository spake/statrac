#!/usr/bin/env python
#
# Copyright 2012 George Caley
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp import util
import datetime
import os
import pickle
import random
import re

from stats import get_probs_stats, fetch_stats

HTML_PATH = os.path.join(os.path.dirname(__file__), 'index.html')

class Page(object):
    def __init__(self, title, url, filename):
        self.title = title
        self.url = url
        self.filename = filename

HOME = Page('Home', '/', 'home.html')
PROBLEMS = Page('Problems', '/problems', 'problems.html')
COMPARE = Page('Compare', '/compare', 'compare.html')
UPDATE = Page('Update', '/update', 'update.html')

PROBLEM = Page('', '/problem/[0-9]+', 'problem.html')

PAGES = [HOME, PROBLEMS, COMPARE, UPDATE]

def standard_template_values():
    template_values = {}

    user = users.get_current_user()

    if user:
        data = get_user_data()
        if data.orac_username:
            nickname = data.orac_username
        else:
            nickname = data.owner.email()

        template_values['nickname'] = nickname
        template_values['logout_url'] = users.create_logout_url('/')
    else:
        template_values['login_url'] = users.create_login_url('/')

    template_values['pages'] = PAGES
    return template_values

class Problem(db.Model):
    prob_id = db.IntegerProperty(required=True)
    name = db.StringProperty(required=True)

class Solution(db.Model):
    prob_id = db.IntegerProperty(required=True)
    owner = db.UserProperty(required=True)
    result = db.IntegerProperty(required=True)
    solve_date = db.DateProperty()

class UserData(db.Model):
    owner = db.UserProperty(required=True)
    orac_username = db.StringProperty()

class StatusUpdate(db.Model):
    owner = db.UserProperty(required=True)
    delta = db.ByteStringProperty(required=True)
    timestamp = db.DateTimeProperty(auto_now_add=True)

def get_user_data(user=None):
    if not user:
        user = users.get_current_user()
    data = memcache.get('userdata-'+user.user_id())
    if not data:
        #data = UserData.all().filter('owner =', user).fetch(1)
        key = userdata_key_name(user)
        data = UserData.get_by_key_name(key)
        if data:
            memcache.add('userdata-'+user.user_id(), data)
        else:
            data = UserData(owner=user, key_name=key)
            data.put()
            memcache.delete('users')
    return data

def set_orac_username(username):
    data = get_user_data()
    if data.orac_username != username:
        data.orac_username = username
        data.put()
        memcache.delete('userdata-'+data.owner.user_id())
        memcache.delete('users')

def problem_key_name(prob_id):
    return str(prob_id)

def solution_key_name(prob_id, owner):
    return str(prob_id)+':'+owner.user_id()

def userdata_key_name(owner):
    return owner.user_id()

def get_problem(prob_id):
    key = 'problem-' + str(prob_id)
    problem = memcache.get(key)
    if not problem:
        problem = Problem.get_by_key_name(problem_key_name(prob_id))
        if problem:
            memcache.add(key, problem)
    return problem

def get_solutions_for_user(user):
    key = 'solutions-for-user-' + user.user_id()
    data = memcache.get(key)
    if not data:
        data = Solution.all().filter('owner =', user).run()
        data = list(data)
        memcache.add(key, data)
    return data

def get_problems_for_user(user):
    key = 'problems-for-user-' + user.user_id()
    probs = memcache.get(key)
    if not probs:
        solns = get_solutions_for_user(user)
        probs = list()
        for soln in solns:
            probs.append(get_problem(soln.prob_id))
        probs = sorted(probs, key=lambda a: a.name)
        memcache.add(key, probs)
    return probs

def login_check(self):
    if not users.get_current_user():
        self.response.set_status(302)
        self.response.headers.add_header('Location', users.create_login_url(self.request.url))
        return False
    return True

def has_problems_check(self):
    if not login_check(self):
        return False
    data = get_user_data()
    if not data.orac_username:
        self.response.set_status(302)
        self.response.headers.add_header('Location', '/?error=noproblems')
        return False
    return True

class HomeHandler(webapp.RequestHandler):
    def get(self):
        template_values = standard_template_values()
        template_values['page'] = HOME
        template_values['error'] = self.request.get('error')

        # get status updates
        update_objects = memcache.get('updates')
        if not update_objects:
            update_objects = list(StatusUpdate.all().order('-timestamp').run(limit=5))
            memcache.add('updates', update_objects)
        # decode deltas into proper strings
        updates = list()
        for update_object in update_objects:
            delta = pickle.loads(update_object.delta)
            last, _, cut = delta[-1]
            if last is None:
                delta = delta[:-1]
            else:
                cut = 0

            username = get_user_data(update_object.owner).orac_username

            solved = list()
            boost = list()
            for name, old, new in delta:
                if new == 100:
                    solved.append(name)
                else:
                    boost.append('%d%% in %s' % (new, name))

            achievements = list()
            if len(solved):
                achievements.append('solved ' + (solved[0] if len(solved) == 1 else ', '.join(solved[:-1]) + ' and ' + solved[-1]))
            if len(boost):
                achievements.append('achieved a new personal best of ' + (boost[0] if len(boost) == 1 else ', '.join(boost[:-1]) + ' and ' + boost[-1]))

            string = username + ' '
            string += achievements[0] if len(achievements) == 1 else achievements[0] + ' and ' + achievements[1]
            string += '.'
            dt = datetime.datetime.strftime(update_object.timestamp + datetime.timedelta(hours=11), "%I:%M%p %A %d %B %Y")
            updates.append((dt, string))

        updates = [('Date', 'Shit')]*5
        template_values['updates'] = updates if len(updates) else None

        self.response.out.write(template.render(HTML_PATH, template_values))

class UpdateHandler(webapp.RequestHandler):
    def get(self):
        if not login_check(self):
            return

        template_values = standard_template_values()
        template_values['page'] = UPDATE
        template_values['status'] = self.request.get('status')
        data = get_user_data()
        template_values['username'] = data.orac_username
        self.response.out.write(template.render(HTML_PATH, template_values))

    def post(self):
        username = self.request.get('username')
        password = self.request.get('password')

        # make sure no-one is using this username already
        user = users.get_current_user()

        result = UserData.all().filter('orac_username =', username).fetch(1)
        if len(result):
            if result[0].owner.user_id() != user.user_id():
                self.response.set_status(303)
                self.response.headers.add_header('Location', '?status=badusername')
                return

        data = fetch_stats(username, password)
        if not data:
            self.response.set_status(303)
            self.response.headers.add_header('Location', '?status=failure')
            return

        uploaded_before = get_user_data().orac_username is not None
        set_orac_username(username)

        stats = get_probs_stats(data)

        problems_changed = False
        memcache.delete('solutions-for-user-' + user.user_id())
        memcache.delete('problems-for-user-' + user.user_id())

        delta = list()

        for prob_id, value in stats.items():
            name, result, solve_date = value
            # check whether this problem exists
            # create it if it doesn't
            key = problem_key_name(prob_id)
            if not Problem.get_by_key_name(key):
                prob = Problem(prob_id=prob_id, name=name, key_name=key)
                prob.put()

            # check whether a solution already exists
            soln_changed = False
            key = solution_key_name(prob_id, user)
            soln = Solution.get_by_key_name(key)
            if soln:
                if soln.result != result:
                    old_result = -1 if not soln.solve_date else soln.result
                    delta.append((name, old_result, result))
                    soln.result = result
                    soln.solve_date = solve_date
                    soln.put()
                    soln_changed = True
            else:
                q = Solution(prob_id=prob_id, owner=user, result=result, solve_date=solve_date, key_name=key)
                q.put()
                soln_changed = True

            if soln_changed:
                memcache.delete('solutions-%d' % prob_id)

        if len(delta) > 0 and uploaded_before:
            # sort the delta by the new score
            # it contains tuples in the format (name, old_result, new_result)
            delta = sorted(delta, key=lambda a:a[2], reverse=True)
            # limit the delta to 5 problems
            total = len(delta)
            limit = 5
            cut = total - limit
            if cut > 0:
                delta = delta[:5]
                delta.append((None, 0, cut))

            delta_bytes = pickle.dumps(delta)
            update = StatusUpdate(delta=delta_bytes, owner=user)
            update.put()
            memcache.delete('updates')

        self.response.set_status(303)
        self.response.headers.add_header('Location', '?status=success')

class ProblemsHandler(webapp.RequestHandler):
    def get(self):
        if not has_problems_check(self):
            return

        template_values = standard_template_values()
        template_values['page'] = PROBLEMS

#        result = memcache.get('problems')
#        if not result:
#            problems = Problem.all()
#            problems.order('name')
#            result = list(problems.run())
#            memcache.add('problems', result)
        result = get_problems_for_user(users.get_current_user())

        total = len(result)
        third = total/3
        two_third = 2*third

        if total % 3 == 1:
            third += 1
            two_third += 1
        elif total % 3 == 2:
            third += 1
            two_third += 2

        template_values['problems'] = (result[:third], result[third:two_third], result[two_third:])
        template_values['no_problems'] = (total == 0)

        self.response.out.write(template.render(HTML_PATH, template_values))

class ProblemHandler(webapp.RequestHandler):
    def get(self):
        if not has_problems_check(self):
            return

        template_values = standard_template_values()
        template_values['page'] = PROBLEM

        prob_id = self.request.url.split('/')[-1]
        template_values['debug'] = prob_id

        if prob_id.isdigit():
            problem = get_problem(prob_id)
        else:
            problem = None

        if problem:
            template_values['problem'] = problem

            # get solutions
            key = 'solutions-' + prob_id
            result = memcache.get(key)
            if not result:
                solns = Solution.all()
                solns.filter('prob_id =', int(prob_id))
                result = list(solns.run())
                memcache.add(key, result)

            # do we have access?
            access = False
            user = users.get_current_user()
            for soln in result:
                if soln.owner == user:
                    access = True
                    break

            solved, unsolved = 0, 0
            scores = dict()
            for soln in result:
                if soln.result == 100:
                    solved += 1
                else:
                    unsolved += 1
                if soln.result not in scores:
                    scores[soln.result] = 0
                scores[soln.result] += 1
            template_values['solved'] = solved
            template_values['unsolved'] = unsolved
            template_values['scores'] = [(result, scores[result]) for result in sorted(scores, reverse=True)]
            template_values['access'] = access

        self.response.out.write(template.render(HTML_PATH, template_values))

class CompareHandler(webapp.RequestHandler):
    def get(self, extra_values=None):
        if not has_problems_check(self):
            return

        template_values = standard_template_values()
        template_values['page'] = COMPARE

        # fetch all users
        users = memcache.get('users')
        if not users:
            users = UserData.all().filter('orac_username !=', None).order('orac_username')
            users = list(users.run())
            memcache.add('users', users)

        real_users = []
        data = get_user_data()
        for user in users:
            if user.orac_username != data.orac_username:
                real_users.append(user)

        template_values['users'] = real_users
        if extra_values:
            for key in extra_values:
                template_values[key] = extra_values[key]

        self.response.out.write(template.render(HTML_PATH, template_values))

    def post(self):
        them_key = self.request.get('them')
        data = list(UserData.all().filter('orac_username =', them_key).run())
        if len(data):
            # get a list of all of their solutions
            our_data = get_user_data()
            their_data = data[0]

            #our_solns = Solution.all().filter('owner =', our_data.owner).run()
            #their_solns = Solution.all().filter('owner =', their_data.owner).run()
            our_solns = get_solutions_for_user(our_data.owner)
            their_solns = get_solutions_for_user(their_data.owner)

            our_solns_dict = dict()
            their_solns_dict = dict()

            for soln in their_solns:
                their_solns_dict[soln.prob_id] = soln

            us_all_count, us_all_total = 0, 0
            us_common_count = 0
            them_all_count, them_all_total = 0, 0
            them_common_count = 0
            common_total = 0

            delta = dict()
            for soln in our_solns:
                if soln.prob_id in their_solns_dict:
                    our_result = soln.result
                    their_result = their_solns_dict[soln.prob_id].result
                    if our_result != their_result:
                        our_date = soln.solve_date
                        their_date = their_solns_dict[soln.prob_id].solve_date

                        problem = get_problem(soln.prob_id)

                        if not our_date and our_result == 0:
                            our_string = 'Not attempted'
                        else:
                            our_string = '%d%%' % our_result

                        if not their_date and their_result == 0:
                            their_string = 'Not attempted'
                        else:
                            their_string = '%d%%' % their_result

                        delta[soln.prob_id] = (problem, our_string, their_string)

                    if our_result == 100:
                        us_common_count += 1
                    if their_result == 100:
                        them_common_count += 1
                    common_total += 1

            table = sorted(delta.values(), key=lambda a:a[0].name)
            extra_values = dict()
            extra_values['table'] = table
            extra_values['us'] = our_data.orac_username
            extra_values['them'] = their_data.orac_username
            extra_values['us_common'] = '%d/%d (%.2f%%)' % (us_common_count, common_total, (us_common_count*100)/float(common_total))
            extra_values['them_common'] = '%d/%d (%.2f%%)' % (them_common_count, common_total, (them_common_count*100)/float(common_total))
            self.get(extra_values)
        else:
            self.response.out.write(them_key)

def main():
    application = webapp.WSGIApplication([
        (HOME.url, HomeHandler),
        (UPDATE.url, UpdateHandler),
        (COMPARE.url, CompareHandler),
        (PROBLEMS.url, ProblemsHandler),
        (PROBLEM.url, ProblemHandler),
        ], debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
