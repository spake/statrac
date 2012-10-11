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
import os
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

PROBLEM = Page('', '', 'problem.html')

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

def get_user_data():
    user = users.get_current_user()
    data = memcache.get('userdata-'+user.user_id())
    if not data:
        data = UserData.all().filter('owner =', user).fetch(1)
        if len(data):
            data = data[0]
            memcache.add('userdata-'+user.user_id(), data)
        else:
            data = UserData(owner=user)
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

class HomeHandler(webapp.RequestHandler):
    def get(self):
        template_values = standard_template_values()
        template_values['page'] = HOME
        snide_remarks = [
                'Welcome to statrac, providing you with orac statistics since before you were born.',
                'If you can read this, then you must have typed the URL in correctly. Nice work!',
                "Scientists haven't yet figured out why this site was made, but they love it all the same.",
                "It's like Hall of Fame, but streamlines the process of laughing at your friends for completing so few problems.",
                "If you're feeling particularly generous today, donate spake some more snide remarks in #aioc."
                ]
        template_values['snide_remark'] = random.choice(snide_remarks)
        self.response.out.write(template.render(HTML_PATH, template_values))

class UpdateHandler(webapp.RequestHandler):
    def get(self):
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

        result = list(UserData.all().filter('orac_username =', username).run())
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

        set_orac_username(username)

        all_prob_ids = memcache.get('all_prob_ids')
        if not all_prob_ids:
            all_prob_ids = set()
            for prob in Problem.all():
                all_prob_ids.add(prob.prob_id)
            memcache.add('all_prob_ids', all_prob_ids)

        stats = get_probs_stats(data)

        all_sols = dict()
        for sol in Solution.all().filter('owner =', user):
            all_sols[sol.prob_id] = sol

        problems_changed = False

        for prob_id, value in stats.items():
            name, result, solve_date = value
            # check whether this problem exists
            # create it if it doesn't
            if prob_id not in all_prob_ids:
                prob = Problem(prob_id=prob_id, name=name)
                prob.put()
                all_prob_ids.add(prob_id)
                problems_changed = True

            # check whether a solution already exists
            sol_changed = False
            if prob_id in all_sols:
                if all_sols[prob_id].result != result:
                    all_sols[prob_id].result = result
                    all_sols[prob_id].solve_date = solve_date
                    all_sols[prob_id].put()
                    sol_changed = True
            else:
                q = Solution(prob_id=prob_id, owner=user, result=result, solve_date=solve_date)
                q.put()
                sol_changed = True

            if sol_changed:
                memcache.delete('solutions-%d' % prob_id)

        # remove problems from memcache
        if problems_changed:
            memcache.delete('problems')
            memcache.delete('all_prob_ids')

        self.response.set_status(303)
        self.response.headers.add_header('Location', '?status=success')

class ProblemsHandler(webapp.RequestHandler):
    def get(self):
        template_values = standard_template_values()
        template_values['page'] = PROBLEMS

        result = memcache.get('problems')
        if not result:
            problems = Problem.all()
            problems.order('name')
            result = list(problems.run())
            memcache.add('problems', result)

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
        template_values = standard_template_values()
        template_values['page'] = PROBLEM

        prob_id = self.request.url.split('/')[-1]
        template_values['debug'] = prob_id

        if prob_id.isdigit():
            key = 'problem-' + prob_id
            result = memcache.get(key)
            if not result:
                problem = Problem.all()
                problem.filter('prob_id =', int(prob_id))
                result = problem.fetch(1)
                memcache.add(key, result)
        else:
            result = []

        if len(result):
            problem = result[0]
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
    def get(self):
        template_values = standard_template_values()
        template_values['page'] = COMPARE

        # fetch all users
        users = memcache.get('users')
        if not users:
            users = UserData.all().filter('orac_username !=', None)
            users = list(users.run())
            memcache.add('users', users)

        real_users = []
        data = get_user_data()
        for user in users:
            if user.orac_username != data.orac_username:
                real_users.append(user)

        template_values['users'] = real_users

        self.response.out.write(template.render(HTML_PATH, template_values))

    def post(self):
        them_key = self.request.get('them')
        data = list(UserData.all().filter('orac_username =', them_key).run())
        if len(data):
            self.response.out.write('woo<br>'+data[0].owner.user_id())
        else:
            self.response.out.write(them_key)

def main():
    application = webapp.WSGIApplication([
        (HOME.url, HomeHandler),
        (UPDATE.url, UpdateHandler),
        (COMPARE.url, CompareHandler),
        (PROBLEMS.url, ProblemsHandler),
        (PROBLEM.url+r'/.*', ProblemHandler),
        ], debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
